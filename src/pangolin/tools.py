"""
Tool implementations for Pangolin agents. Each tool is a simple Python
function that replaces a Claude Code CLI built-in. Fully auditable, testable,
deterministic.

Security: tools enforce path restrictions from modes.yml. A tool that
tries to read/write outside the declared paths raises PermissionError.
This is the hard barrier — no CLI flag dependency (eliminates A.CLAUDE_CLI).
"""

from __future__ import annotations

import glob as globmod
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .providers import ToolResult


CONTAINER_IMAGE = "pangolin-agent-bash"


# Map modes.yml tool identifiers to Claude Code CLI tool names.
# Used by the container CLI path in orchestrate.py to translate
# --allowedTools values. The Python TOOL_REGISTRY below uses the
# modes.yml identifiers directly and doesn't need this mapping.
CLI_TOOL_NAMES: dict[str, str] = {
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "glob": "Glob",
    "grep": "Grep",
    "bash": "Bash",
    "web_search": "WebSearch",
    "web_fetch": "WebFetch",
}


@dataclass
class ToolConfig:
    """Security constraints for tool execution, derived from modes.yml."""
    repo_root: Path
    readable_paths: list[str] = field(default_factory=list)
    writable_paths: list[str] = field(default_factory=list)
    code_execution: bool = False
    container_runtime: str | None = None  # "runsc" for gVisor
    network: bool = False
    # Issue numbers the agent is allowed to report as "processed". Used by
    # the report_processed tool. Empty set = the agent cannot report
    # anything (e.g. wiki-ingest, which is file-driven, not issue-driven).
    processed_eligible: set[int] = field(default_factory=set)

    def _resolve(self, path: str) -> Path:
        """Resolve a path relative to repo root, prevent traversal."""
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.repo_root / p).resolve()
        # Must stay within repo_root
        try:
            resolved.relative_to(self.repo_root.resolve())
        except ValueError:
            raise PermissionError(f"Path traversal blocked: {path}")
        return resolved

    def _is_under(self, resolved: Path, allowed_path: str) -> bool:
        """Check if resolved path is equal to or inside allowed_path.
        Uses Path.is_relative_to() — no string prefix matching."""
        target = (self.repo_root / allowed_path.rstrip("/")).resolve()
        return resolved == target or resolved.is_relative_to(target)

    def check_readable(self, path: str) -> Path:
        resolved = self._resolve(path)
        if any(self._is_under(resolved, rp) for rp in self.readable_paths):
            return resolved
        raise PermissionError(f"Read denied: {path} (not in readable_paths)")

    def check_writable(self, path: str) -> Path:
        resolved = self._resolve(path)
        if any(self._is_under(resolved, wp) for wp in self.writable_paths):
            return resolved
        raise PermissionError(f"Write denied: {path} (not in writable_paths)")


class ToolExecutor:
    """Executes tool calls within security constraints."""

    def __init__(self, config: ToolConfig, enabled_tools: set[str]):
        self.config = config
        self.enabled = enabled_tools
        # Accumulator: issue numbers the agent has reported as processed
        # via the report_processed tool during this run. Read by the
        # orchestrator after provider.chat() returns.
        self.processed: list[int] = []
        # Track every path the agent successfully wrote/edited during this run.
        # The orchestrator's inference-based closing uses this as a "did
        # anything" signal for thinking/writing modes.
        self.written_files: set[str] = set()
        self._handlers = {
            "read": self._read,
            "write": self._write,
            "edit": self._edit,
            "glob": self._glob,
            "grep": self._grep,
            "bash": self._bash,
            "report_processed": self._report_processed,
        }

    def execute(self, tool_name: str, args: dict) -> ToolResult:
        """Execute a tool call, return the result."""
        name = tool_name.lower()
        if name not in self.enabled:
            return ToolResult(
                tool_use_id="",
                content=f"Tool '{tool_name}' is not available in this mode.",
                is_error=True,
            )
        handler = self._handlers.get(name)
        if not handler:
            return ToolResult(
                tool_use_id="",
                content=f"Unknown tool: {tool_name}",
                is_error=True,
            )
        try:
            result = handler(args)
            return ToolResult(tool_use_id="", content=result)
        except PermissionError as e:
            return ToolResult(tool_use_id="", content=str(e), is_error=True)
        except Exception as e:
            return ToolResult(
                tool_use_id="", content=f"Error: {type(e).__name__}: {e}", is_error=True
            )

    def get_tool_definitions(self) -> list[dict]:
        """Return Anthropic-format tool definitions for enabled tools."""
        all_defs = {
            "read": {
                "name": "read",
                "description": "Read a file's contents. Returns the text content of the file at the given path.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to read"},
                        "offset": {"type": "integer", "description": "Start line (0-based)"},
                        "limit": {"type": "integer", "description": "Max lines to read"},
                    },
                    "required": ["path"],
                },
            },
            "write": {
                "name": "write",
                "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
            "edit": {
                "name": "edit",
                "description": "Replace a string in a file. The old_string must appear exactly once in the file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to edit"},
                        "old_string": {"type": "string", "description": "Text to find"},
                        "new_string": {"type": "string", "description": "Replacement text"},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
            "glob": {
                "name": "glob",
                "description": "Find files matching a glob pattern. Returns matching file paths.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g., '**/*.md')"},
                        "path": {"type": "string", "description": "Directory to search in"},
                    },
                    "required": ["pattern"],
                },
            },
            "grep": {
                "name": "grep",
                "description": "Search file contents for a regex pattern. Returns matching lines.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern"},
                        "path": {"type": "string", "description": "File or directory to search"},
                        "include": {"type": "string", "description": "File glob filter"},
                    },
                    "required": ["pattern"],
                },
            },
            "bash": {
                "name": "bash",
                "description": "Execute a bash command and return its output.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Bash command to run"},
                    },
                    "required": ["command"],
                },
            },
            "report_processed": {
                "name": "report_processed",
                "description": (
                    "Report the GitHub issue numbers you have fully processed in this run. "
                    "Call this once near the end. Pass only issue numbers that were in the "
                    "ISSUES list given to you. The orchestrator will close those issues "
                    "with a summary comment after the cycle PR is created. Numbers outside "
                    "your input set are silently dropped."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "numbers": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Issue numbers handled in this run.",
                        },
                    },
                    "required": ["numbers"],
                },
            },
        }
        return [all_defs[t] for t in self.enabled if t in all_defs]

    # ── Tool implementations ──

    def _read(self, args: dict) -> str:
        path = self.config.check_readable(args["path"])
        if not path.exists():
            raise FileNotFoundError(f"File not found: {args['path']}")
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        offset = args.get("offset", 0)
        limit = args.get("limit", len(lines))
        selected = lines[offset : offset + limit]
        return "".join(selected)

    def _write(self, args: dict) -> str:
        path = self.config.check_writable(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        self.written_files.add(args["path"])
        return f"Wrote {len(args['content'])} bytes to {args['path']}"

    def _edit(self, args: dict) -> str:
        path = self.config.check_writable(args["path"])
        # Also need read access to edit
        self.config.check_readable(args["path"])
        text = path.read_text(encoding="utf-8")
        old = args["old_string"]
        new = args["new_string"]
        count = text.count(old)
        if count == 0:
            raise ValueError(f"old_string not found in {args['path']}")
        if count > 1:
            raise ValueError(f"old_string appears {count} times in {args['path']} (must be unique)")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        self.written_files.add(args["path"])
        return f"Edited {args['path']}"

    def _glob(self, args: dict) -> str:
        # Base path must be in readable_paths — otherwise the agent could
        # enumerate file *names* anywhere in the repo (e.g. via Glob on `.`).
        # Filenames are sometimes themselves sensitive (client folders etc.).
        base = args.get("path", ".")
        base_resolved = self.config.check_readable(base)
        pattern = args["pattern"]
        matches = sorted(globmod.glob(str(base_resolved / pattern), recursive=True))
        # Return relative paths, and additionally drop matches whose realised
        # path falls outside readable_paths (defensive: pattern could escape).
        root = str(self.config.repo_root.resolve())
        rel_matches = []
        for m in matches:
            if not os.path.isfile(m):
                continue
            try:
                self.config.check_readable(os.path.relpath(m, root))
            except PermissionError:
                continue
            rel_matches.append(os.path.relpath(m, root))
        return "\n".join(rel_matches[:500]) if rel_matches else "No matches found."

    def _grep(self, args: dict) -> str:
        # Base path must be in readable_paths (same reason as in _glob).
        search_path = args.get("path", ".")
        resolved = self.config.check_readable(search_path)
        pattern = args["pattern"]
        include = args.get("include", "")

        # subprocess uses list-args (no shell), so `pattern` and `include`
        # are passed verbatim as argv entries — no shell injection. The
        # 10s timeout caps catastrophic regex backtracking.
        cmd = ["grep", "-rn", "-E", pattern, str(resolved)]
        if include:
            cmd.insert(3, f"--include={include}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.stdout[:10000] if result.stdout else "No matches found."
        except subprocess.TimeoutExpired:
            return "Search timed out."

    def _bash(self, args: dict) -> str:
        if not self.config.code_execution:
            raise PermissionError("Bash execution not allowed in this mode")
        cmd = args["command"]
        if self.config.container_runtime:
            return self._bash_in_container(cmd)
        try:
            result = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True, text=True, timeout=120,
                cwd=str(self.config.repo_root),
            )
            output = result.stdout + result.stderr
            return output[:20000] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out (120s limit)."

    def _report_processed(self, args: dict) -> str:
        """Record processed issue numbers — cross-checked against eligible set.

        This is the OOB replacement for the old in-band `PROCESSED: #N` line.
        Going through the tool-call path means: the orchestrator never
        parses agent free-text for control-plane data, prompt-injection
        forging the marker is impossible (an injection that wants to close
        an issue would have to invoke this tool, and the eligibility check
        catches that), and every report is logged as a normal tool call.
        """
        eligible = self.config.processed_eligible
        raw = args.get("numbers") or []
        accepted: list[int] = []
        rejected: list[int] = []
        for n in raw:
            if not isinstance(n, int):
                rejected.append(n)
                continue
            if n in eligible:
                accepted.append(n)
            else:
                rejected.append(n)
        # De-duplicate while preserving order
        for n in accepted:
            if n not in self.processed:
                self.processed.append(n)
        msg = f"Recorded as processed: {accepted}"
        if rejected:
            msg += f" (rejected, not in your input set: {rejected})"
        return msg


    def _bash_in_container(self, cmd: str) -> str:
        """Run a bash command inside a gVisor-sandboxed container."""
        repo = str(self.config.repo_root.resolve())
        docker_cmd = [
            "docker", "run", "--rm",
            f"--runtime={self.config.container_runtime}",
            "--read-only",
            "--cap-drop=ALL",
            "--tmpfs", "/tmp:noexec,nosuid,size=64m",
            "--user", "1000",
            "--pids-limit", "128",
            "--memory", "512m",
            "--cpus", "1.0",
        ]
        if not self.config.network:
            docker_cmd += ["--network=none"]
        # Base mount: repo read-only
        docker_cmd += ["-v", f"{repo}:/repo:ro"]
        # Writable paths: bind-mount read-write over the ro base
        for wp in self.config.writable_paths:
            host_path = (self.config.repo_root / wp.rstrip("/")).resolve()
            container_path = f"/repo/{wp.rstrip('/')}"
            docker_cmd += ["-v", f"{host_path}:{container_path}:rw"]
        docker_cmd += ["-w", "/repo", CONTAINER_IMAGE, "bash", "-c", cmd]
        try:
            result = subprocess.run(
                docker_cmd, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr
            return output[:20000] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out (120s limit)."

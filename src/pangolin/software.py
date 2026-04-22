#!/usr/bin/env python3
"""
Software task runner. Picks up one mode:software issue, creates a
feature branch, runs the agent with Bash+tools, commits, opens PR.

Called from `run_cycle()` after the main cycle PR is opened.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


from pangolin.core import REPO, gh, make_logger
from pangolin.modes import load_modes
from pangolin.paths import resolve_config
from pangolin.providers import create_provider
from pangolin.tools import ToolConfig, ToolExecutor

log = make_logger("software")


def _verified_paths(agent_output: str) -> list[str]:
    """Parse `VERIFIED: path1, path2, ...` out of the agent's final message.
    Empty list if the line is absent or malformed. Case-insensitive."""
    for line in agent_output.splitlines():
        stripped = line.strip()
        head, _, rest = stripped.partition(":")
        if head.strip().upper() == "VERIFIED":
            return [p.strip() for p in rest.split(",") if p.strip()]
    return []


def _stage_and_check() -> tuple[bool, list[str]]:
    """Stage software-mode writable paths and return (changes_present, staged_paths)."""
    subprocess.run(
        ["git", "add", "src/", "tests/", "scripts/"],
        cwd=str(REPO), capture_output=True,
    )
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    staged = [ln for ln in out.stdout.splitlines() if ln.strip()]
    return (len(staged) > 0, staged)


def _spawn_and_verify(mode, ssot: str, prompt: str, *, max_attempts: int = 2) -> bool:
    """Spawn the software container, cross-check agent's VERIFIED claim
    against actual staged changes, retry once on hallucination.

    Returns True if changes were staged (caller proceeds to commit/push/PR),
    False if even the retry produced no changes (caller aborts).

    Hallucination signature: agent's final message contains `VERIFIED: <path>`
    but `git diff --cached` is empty. The retry prompt calls this out
    explicitly so the agent gets one more chance to actually invoke Write.
    """
    from pangolin.orchestrate import spawn_agent_container_tooluse

    attempt = 1
    current_prompt = prompt
    while attempt <= max_attempts:
        result = spawn_agent_container_tooluse(mode, ssot, current_prompt)
        agent_out = result.get("result", "") if isinstance(result, dict) else ""
        changed, staged = _stage_and_check()
        if changed:
            if attempt > 1:
                log(f"retry succeeded on attempt {attempt} — {len(staged)} path(s) staged")
            return True

        verified = _verified_paths(agent_out)
        if not verified:
            log(f"no changes and no VERIFIED: footer — agent did not attempt the task")
            return False
        if attempt >= max_attempts:
            log(f"🔴 retry exhausted: agent claimed VERIFIED: {verified} but no files staged")
            return False

        log(f"⚠️ hallucinated VERIFIED: {verified} but no changes staged — retrying ({attempt+1}/{max_attempts})")
        current_prompt = (
            prompt
            + "\n\n--- RETRY ---\n"
            + "Your previous response contained a `VERIFIED:` footer, but the "
            + "host-side orchestrator detected NO actual file changes on disk. "
            + "This means you did not truly invoke the `Write` tool — your "
            + "last message was a plausible-sounding text description without "
            + "the corresponding tool-call. This is your second and final "
            + "attempt. Invoke the `Write` tool with the real file content "
            + "NOW, then use `Bash` to `ls -la` and `cat` the file to confirm "
            + "it is on disk. Only then emit the `VERIFIED:` footer."
        )
        attempt += 1
    return False


def _branch_for_task(number: int, title: str) -> str:
    """Build a git-safe branch name from an issue number + title.

    Previously the code did `title.lower().replace(" ", "-")[:40]`, which
    left colons intact. A title like `software: add X` produced
    `task/12-software:-add-x` — `git push` parses that as a src:dst
    refspec and rejects it. Strip everything that isn't alphanumeric
    or `-`, collapse runs, trim edges.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")[:40].strip("-")
    return f"task/{number}-{slug}" if slug else f"task/{number}"


def run():
    modes = load_modes()
    mode = modes["software"]

    # Find oldest mode:software issue
    tasks = gh("issue", "list", "--state", "open", "--label", "mode:software",
               "--limit", "1", "--json", "number,title,body,labels")
    task_list = json.loads(tasks) if tasks else []
    if not task_list:
        log("no software tasks")
        return

    task = task_list[0]
    number = task["number"]
    branch = _branch_for_task(number, task["title"])
    log(f"picked up: #{number}")

    # Create branch
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(REPO), capture_output=True)

    ssot = resolve_config("docs/software-agent.md").read_text()
    prompt = f"{ssot}\n\n--- TASK ---\n{json.dumps(task)}\n\nImplement the task. Run tests if they exist."

    # Two paths, OAuth preferred:
    # - OAuth (CLAUDE_CODE_OAUTH_TOKEN): claude CLI runs inside
    #   pangolin-agent-software (CLI + bash, no shell-not-found loop). Outbound
    #   is gated by the egress proxy. Subscription billing.
    # - API key fallback (ANTHROPIC_API_KEY): in-process anthropic SDK on the
    #   host with ToolExecutor. Bash tool delegates to pangolin-agent-bash
    #   (no-network) for sandboxed shell execution. Per-token billing.
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        from pangolin.orchestrate import spawn_agent_container_tooluse
        if not _spawn_and_verify(mode, ssot, prompt):
            return
        log("agent done: OAuth/CLI path (pangolin-agent-software)")
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider = create_provider(mode.provider)
        config = ToolConfig(
            repo_root=REPO,
            readable_paths=mode.readable_paths,
            writable_paths=mode.writable_paths,
            code_execution=mode.code_execution,
            container_runtime=mode.container_runtime,
            network=mode.network,
        )
        executor = ToolExecutor(config, set(mode.allowed_tools))
        tools = executor.get_tool_definitions()
        result = provider.chat(
            system="You are the software bot.",
            user=prompt,
            tools=tools,
            model=mode.model,
            tool_executor=executor,
        )
        log(f"agent done: API-key path ({result.tool_calls} tool calls)")
        # Stage + early-return for the SDK path (no retry here — the SDK
        # path uses in-process ToolExecutor, so writes can't hallucinate).
        subprocess.run(
            ["git", "add", "src/", "tests/", "scripts/"],
            cwd=str(REPO), capture_output=True
        )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=str(REPO), capture_output=True
        )
        if diff.returncode == 0:
            log("no changes")
            return
    else:
        log("skip: no CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY in env")
        return

    subprocess.run(
        ["git", "commit", "-m", f"task #{number}: {task['title']}"],
        cwd=str(REPO), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "push", "origin", branch],
        cwd=str(REPO), capture_output=True, check=True
    )

    repo_name = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")
    os.environ["GH_REPO"] = repo_name

    # AGENT_MARKER in body: how `pr_feedback.run()` detects this as an
    # agent-authored PR. Without it, owner comments on the PR are
    # invisible to the feedback loop and the PR can't be iterated on.
    from pangolin.core import wrap_agent_body
    pr_body = wrap_agent_body(f"Automated code task for #{number}.")
    pr_url = gh("pr", "create", "--title", f"task #{number}: {task['title']}",
                "--body", pr_body,
                "--base", "main", "--head", branch)
    gh("issue", "comment", str(number), "--body",
       f"🤖 **software-agent**: PR erstellt — {pr_url}")
    log(f"PR: {pr_url}")


if __name__ == "__main__":
    run()

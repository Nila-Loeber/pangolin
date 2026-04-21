"""Shared helpers used by multiple pangolin entry points.

Nothing in this module depends on provider/tool machinery — just pure utility
code that both the cycle orchestrator and the software-task runner need.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Resolve the repo root via git. Robust against symlinks and worktrees."""
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    )
    return Path(out.strip()).resolve()


REPO = _repo_root()


# Sentinel prepended to every comment the orchestrator/software agent posts on
# GitHub issues. Used by downstream pre-filters to recognise bot-origin
# activity (PAT-based `gh issue comment` shows the Owner as author, defeating
# the standard "[bot]" login check — we need a content marker instead).
AGENT_MARKER = "<!-- pangolin:auto -->"


def wrap_agent_body(body: str) -> str:
    """Prepend the AGENT_MARKER to a body if not already present."""
    if AGENT_MARKER in body:
        return body
    return f"{AGENT_MARKER}\n{body}"


def make_logger(prefix: str):
    """Create a log() function that prefixes every message with `[prefix]`."""
    def log(msg: str) -> None:
        print(f"[{prefix}] {msg}", flush=True)
    return log


def gh(*args: str, check: bool = True, timeout: int = 60) -> str:
    """Run gh CLI command, return stdout.

    If the call fails we log a loud, unambiguous error line that includes
    the command args, exit code, stderr, and stdout. Callers that pass
    `check=False` still get this diagnostic — a silent return-empty on
    failure was the root cause of "cycle green but no PR created" on the
    2026-04-21 canary after pr-feedback merged. We don't raise here so
    callers can still decide (e.g. "no issue to edit" is a non-fatal
    gh failure for some code paths), but *the log* is always loud.
    """
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True,
        cwd=str(REPO), timeout=timeout,
    )
    if result.returncode != 0:
        # Truncate very long bodies so one bad call doesn't blow the log.
        stderr = (result.stderr or "")[:1000]
        stdout = (result.stdout or "")[:1000]
        print(
            f"🔴 gh FAILED: gh {' '.join(args[:3])}... "
            f"exit={result.returncode} stderr={stderr!r} stdout={stdout!r}",
            file=sys.stderr, flush=True,
        )
    return result.stdout.strip()

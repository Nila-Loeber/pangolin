"""Shared helpers used by multiple sandburg entry points.

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
AGENT_MARKER = "<!-- sandburg:auto -->"


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

    If `check` is True and the call fails, the error is written to stderr
    so GHA surfaces it in red; we don't raise so callers can continue with
    the empty-string result.
    """
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True,
        cwd=str(REPO), timeout=timeout,
    )
    if check and result.returncode != 0:
        print(f"gh error: {result.stderr[:200]}", file=sys.stderr, flush=True)
    return result.stdout.strip()

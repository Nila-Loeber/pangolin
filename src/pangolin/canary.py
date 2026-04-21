"""`pangolin canary-update` — one-shot "update shim, run build, run cycle, report".

Runs inside a wiki repo (e.g. test-pangolin). Assumes the caller has a `gh`
auth context that can dispatch workflows in BOTH the wiki repo AND the
upstream pangolin repo (PAT with `workflow` scope, or a user-level
`gh auth login`). The local Claude Code agent on the owner's machine has
this naturally.

Use-case: owner says "gibt update, teste mal" → agent invokes this command
via the `canary-update` skill (scaffolded into `.claude/skills/` by
`pangolin init`) and relays the final status.

Flow:
1. Refresh `.github/workflows/agent-cycle.yml` from the installed package
   (wiki repo may have a stale copy; the package is SSoT).
2. Commit + push if the shim changed.
3. Dispatch `build-agent-images` on the pangolin upstream; wait.
4. Dispatch `agent-cycle` on the wiki repo; wait.
5. Report per-run conclusion + the URL for drilling into logs.

Non-goals (scope creep candidates, not MVP):
- Detecting "no Containerfile change, skip build" — cached GHA layers make
  a no-op build fast; skipping complicates the logic more than it saves.
- Handling external-contributor forks — owner-driven canary is always
  same-origin.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

from pangolin.core import REPO, gh, make_logger
from pangolin.paths import default_workflows_dir

log = make_logger("canary")

UPSTREAM_REPO = os.environ.get("PANGOLIN_UPSTREAM_REPO", "Nila-Loeber/pangolin")
BUILD_WORKFLOW = "build-agent-images"
CYCLE_WORKFLOW = "agent-cycle"
# Seconds to wait after dispatch for the run to register with the GH API.
# `gh run list` can return stale data if we query too quickly.
DISPATCH_SETTLE_SECONDS = 4


def _refresh_shim() -> bool:
    """Copy the package's workflow template over the wiki's local copy.
    Returns True if anything actually changed."""
    src = default_workflows_dir() / "agent-cycle.yml"
    dst = REPO / ".github" / "workflows" / "agent-cycle.yml"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.read_bytes() == src.read_bytes():
        return False
    shutil.copy2(src, dst)
    return True


def _commit_shim_changes() -> bool:
    """Commit + push any pending changes in the wiki repo. Returns True
    if a commit was made."""
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(REPO),
        capture_output=True, text=True, check=True,
    )
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "add", "-A"], cwd=str(REPO), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "bump pangolin shim (canary-update)"],
        cwd=str(REPO), check=True, capture_output=True,
    )
    subprocess.run(["git", "push"], cwd=str(REPO), check=True, capture_output=True)
    return True


def _latest_run_id(repo: str, workflow: str) -> str | None:
    """Most recent run of `workflow` on `repo`. Empty string means the GH
    API hasn't registered the dispatch yet — caller retries."""
    raw = gh(
        "-R", repo, "run", "list",
        "--workflow", workflow, "--limit", "1",
        "--json", "databaseId",
        "-q", ".[0].databaseId",
        check=False,
    )
    return raw.strip() or None


def _dispatch_and_wait(repo: str, workflow: str, ref: str = "main") -> tuple[str, str, str]:
    """Dispatch `workflow` on `repo`@`ref`, wait for it, return
    (run_id, conclusion, html_url). conclusion is 'success', 'failure',
    'cancelled', etc."""
    log(f"dispatching {workflow} on {repo}@{ref}")
    gh("-R", repo, "workflow", "run", workflow, "--ref", ref, check=False)

    # Settle: the run takes a moment to show up in `gh run list`.
    run_id = None
    for _ in range(5):
        time.sleep(DISPATCH_SETTLE_SECONDS)
        run_id = _latest_run_id(repo, workflow)
        if run_id:
            break
    if not run_id:
        raise RuntimeError(f"{workflow} dispatch did not register within ~20s")

    log(f"  run {run_id} — watching")
    subprocess.run(
        ["gh", "-R", repo, "run", "watch", run_id, "--exit-status"],
        check=False,  # we read the conclusion explicitly below
    )
    view_json = gh(
        "-R", repo, "run", "view", run_id,
        "--json", "conclusion,url",
        check=False,
    )
    if not view_json:
        return run_id, "unknown", ""
    data = json.loads(view_json)
    return run_id, data.get("conclusion") or "unknown", data.get("url") or ""


def run() -> int:
    """Entry point for `pangolin canary-update`. Returns:
       0 — all steps succeeded,
       1 — shim refreshed but a workflow run failed,
       2 — couldn't dispatch at all (auth / network)."""
    log("===> refreshing workflow shim from package")
    if _refresh_shim():
        log("  shim updated")
    else:
        log("  shim unchanged")

    if _commit_shim_changes():
        log("  committed + pushed shim changes")
    else:
        log("  nothing to commit")

    overall = 0
    try:
        _, build_conc, build_url = _dispatch_and_wait(UPSTREAM_REPO, BUILD_WORKFLOW)
    except Exception as e:
        log(f"build-agent-images dispatch failed: {e}")
        return 2
    log(f"===> build-agent-images: {build_conc}  {build_url}")
    if build_conc != "success":
        overall = 1
        log("aborting canary-update — cycle needs fresh images")
        _report(build_conc, build_url, None, None)
        return overall

    try:
        # The wiki-repo workflow runs in the current repo. gh uses the
        # repo of the cwd when -R is omitted.
        cycle_repo = _wiki_repo_slug()
        _, cycle_conc, cycle_url = _dispatch_and_wait(cycle_repo, CYCLE_WORKFLOW)
    except Exception as e:
        log(f"agent-cycle dispatch failed: {e}")
        return 2
    log(f"===> agent-cycle: {cycle_conc}  {cycle_url}")
    if cycle_conc != "success":
        overall = 1

    _report(build_conc, build_url, cycle_conc, cycle_url)
    return overall


def _wiki_repo_slug() -> str:
    """Resolve the wiki repo's `owner/name` from the git remote."""
    return gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner")


def _report(build_conc, build_url, cycle_conc, cycle_url) -> None:
    """Final summary — the skill relays this to the owner."""
    print()
    print("=== canary-update summary ===")
    print(f"  build-agent-images: {build_conc}")
    if build_url:
        print(f"    {build_url}")
    if cycle_conc is not None:
        print(f"  agent-cycle:        {cycle_conc}")
        if cycle_url:
            print(f"    {cycle_url}")


if __name__ == "__main__":
    sys.exit(run())

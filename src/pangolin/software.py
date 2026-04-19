#!/usr/bin/env python3
"""
Software task runner. Picks up one mode:software issue, creates a
feature branch, runs the agent with Bash+tools, commits, opens PR.

Called from `run_cycle()` after the main cycle PR is opened.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


from pangolin.core import REPO, gh, make_logger
from pangolin.modes import load_modes
from pangolin.providers import create_provider
from pangolin.tools import ToolConfig, ToolExecutor

log = make_logger("software")


def run():
    modes = load_modes(REPO / "modes.yml")
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
    title = task["title"].lower().replace(" ", "-")[:40]
    branch = f"task/{number}-{title}"
    log(f"picked up: #{number}")

    # Create branch
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(REPO), capture_output=True)

    # Run agent
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

    ssot = (REPO / "docs/software-agent.md").read_text()
    prompt = f"{ssot}\n\n--- TASK ---\n{json.dumps(task)}\n\nImplement the task. Run tests if they exist."

    result = provider.chat(
        system="You are the software bot.",
        user=prompt,
        tools=tools,
        model=mode.model,
        tool_executor=executor,
    )
    log(f"agent done: {result.tool_calls} tool calls")

    # Commit + push + PR
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

    pr_url = gh("pr", "create", "--title", f"task #{number}: {task['title']}",
                "--body", f"Automated code task for #{number}.",
                "--base", "main", "--head", branch)
    gh("issue", "comment", str(number), "--body",
       f"🤖 **software-agent**: PR erstellt — {pr_url}")
    log(f"PR: {pr_url}")


if __name__ == "__main__":
    run()

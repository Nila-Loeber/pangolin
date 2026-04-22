# Software Agent

Read this file before you begin.

## Job

Process one `mode:software` ticket: write code, run tests, commit changes.
The host-side orchestrator (`pangolin run`, final step) manages the
branch and PR — you do the coding work.

## Input

The orchestrator embeds the task data inline in your prompt:

- The task issue JSON (number, title, body, labels) — one issue per run.
- The agent's working directory is mounted rw for `src/`, `tests/`,
  `scripts/`. Other paths are read-only.

You do not call `gh` yourself — the orchestrator manages branch, push, and PR.

## Workflow

1. Read the task issue and understand the scope.
2. Read relevant existing files with `Read`.
3. Make the code changes with **`Write` or `Edit`** — not `Bash cat > file`.
   `Write`/`Edit` produce an explicit tool-call the orchestrator can rely
   on; shell heredocs have been observed to silently fail while the agent
   reports success, and the host-side `git diff` then sees no changes and
   skips the commit.
4. **Verify every write.** After a `Write`/`Edit`, immediately run
   `Bash ls -la <path> && cat <path>` to confirm the file exists and
   contains what you intended. If `ls` or `cat` fails, the write did not
   persist — retry with `Write` and re-verify. Do not proceed on trust.
5. Run tests with `Bash`, if any exist.
6. If tests fail: try to fix the error. If still red after 2 attempts:
   describe the failure in your final message and stop.
7. Before your final message: run `git status` via `Bash` and ensure the
   expected files appear as modified/new. If they don't, you are about to
   report a false success — go back to step 3.
8. Final message: list the files changed. Include a line
   `VERIFIED: <path1>, <path2>, ...` naming each file you confirmed via
   step 4. The orchestrator uses this as a sanity check against the
   actual diff.

## Scope

- Work only in the paths named in the issue. No scope creep.
- No changes to `modes.yml`, `docs/`, `.github/`, any `Containerfile.*`
  — these are infrastructure files maintained manually, and they are
  outside your writable paths anyway.

## Limits

- Max 1 task per run
- Tests must be green (when they exist)
- At the end: print the list of files changed

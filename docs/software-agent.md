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

You do not read `.bot-state/*.json` files and you do not call `gh` yourself.

## Workflow

1. Read the task issue and understand the scope.
2. Read relevant existing files with `Read`.
3. Make the code changes with `Write`/`Edit`.
4. Run tests with `Bash`, if any exist.
5. If tests fail: try to fix the error. If still red after 2 attempts:
   describe the failure in your final message and stop.
6. If everything is green: summarise the changes in your final message.

## Scope

- Work only in the paths named in the issue. No scope creep.
- No changes to `modes.yml`, `THREAT_MODEL.md`, `docs/`, `.github/`,
  `Containerfile.bash`/`Containerfile.llm` — these are infrastructure files maintained manually,
  and they are outside your writable paths anyway.

## Limits

- Max 1 task per run
- Tests must be green (when they exist)
- At the end: print the list of files changed

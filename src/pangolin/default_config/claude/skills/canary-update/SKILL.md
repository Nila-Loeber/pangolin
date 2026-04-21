---
name: canary-update
description: Update this wiki repo to the latest pangolin main and run a full canary cycle (build-agent-images + agent-cycle), then report back. Use this when the owner says "update und teste", "canary", "teste mal das update", "gibt nen update, teste mal", or any equivalent natural-language request to pull the latest pangolin and exercise it end-to-end.
---

# Canary-update skill

When invoked, run `pangolin canary-update` in this wiki repo and report the result.

The CLI:
1. refreshes `.github/workflows/agent-cycle.yml` from the installed package (pangolin is SSoT),
2. commits + pushes if the shim changed,
3. dispatches `build-agent-images` on the pangolin upstream (`Nila-Loeber/pangolin`), waits for completion,
4. dispatches `agent-cycle` here, waits,
5. prints a `=== canary-update summary ===` block with per-run conclusions + URLs.

Relay that summary back to the owner verbatim — it already contains the
URLs they can click. If either step was not `success`:
1. pull the failing run's log tail via `gh run view <run-id> -R <repo> --log-failed`
   (the summary printed by the CLI gives you both the run URL and the repo),
2. paste the last ~20 lines and a one-sentence hypothesis of the cause.

Pre-flight: if `pangolin canary-update` exits with "command not found" or a
pre-atomic-deploy stack trace, the local package is stale. Bump it first:
```bash
pip install --upgrade git+https://github.com/Nila-Loeber/pangolin.git@main
```
then re-run `pangolin canary-update`.

Auth expectation: the user's local `gh auth` context needs to cover BOTH
this repo (dispatch + push) AND the pangolin upstream (dispatch). A
user-level `gh auth login` covers both; a default `GITHUB_TOKEN` in CI
would not. If dispatch on the upstream returns 403, fall back to: dispatch
agent-cycle only, and tell the owner the build needs to be kicked on
pangolin/Actions manually.

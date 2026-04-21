# Deploy-prompt for AI agents

Copy this whole file into your agent's context when asking it to install
pangolin into an existing wiki repo. The README has a condensed version
for quick reference; this is the long form with edge-case coverage.

---

**Task: Deploy pangolin to an existing wiki repo.**

Pangolin is an owner-triggered conversational-loop CLI that drops into any
Git wiki repo and runs a research/ingest/think/write/PR cycle on dispatch.
Upstream: `https://github.com/Nila-Loeber/pangolin`. The full deploy
walkthrough is in that repo's `README.md` — read it first.

**What I'm asking you to do:** scaffold pangolin into the wiki repo the
owner hands you, commit the scaffolding cleanly, and stop at the point
where the owner needs to do non-automatable steps (secrets, repo
settings, first dispatch).

**Required from the owner before you start:**

- Path to the local clone of the wiki repo.
- Confirmation: is there already meaningful content in `wiki/`?
  (Determines whether you pass `--with-wiki` to `pangolin init` — only
  pass it for empty/new wikis; it seeds the nlkw-style template that
  would collide with existing content.)

**Steps:**

1. **Install the package**:
   `pip install git+https://github.com/Nila-Loeber/pangolin.git@main`.
   Verify `pangolin version` prints. Stay on `main` — the owner can pin
   `PANGOLIN_REF` to a SHA later.

2. **Scaffold**: from the wiki repo root, run `pangolin init` (NOT
   `--force`, NOT `--with-wiki` for existing-content wikis). This adds
   `.github/workflows/agent-cycle.yml`, `wiki/SCHEMA.md` if missing,
   empty-dir markers for `wiki/fragment/`, `notes/ideas/`, `drafts/`,
   `content/`, and `.ingest-watermark`. Print the full stdout so the
   owner sees what changed vs skipped.

3. **Read SCHEMA.md + agent-cycle.yml diffs if files pre-existed.** If
   the wiki already had an old pangolin setup, `pangolin init` will
   have skipped them — run `pangolin refresh-workflows` and show the
   diff. Do NOT commit conflicting changes silently.

4. **Check `.gitignore`** — add `.env`, `.venv/`, `.DS_Store` if
   missing. Don't touch if already present.

5. **(Optional) modes.override.yml**: ask the owner if they want the
   package-default models (Sonnet for thinking/writing direct modes) or
   Opus (slower but higher quality). If Opus:
   ```yaml
   modes:
     thinking: { model: claude-opus-4-7 }
     writing:  { model: claude-opus-4-7 }
   ```
   Default is fine; skip if owner has no preference.

6. **Commit**: `git add -A && git commit -m "feat: initialize pangolin"`.
   Review the diff with the owner BEFORE pushing — this is the
   pangolin-onboarding commit that shows up in their history.

7. **Push.**

8. **STOP and tell the owner they must do two things manually** (you
   cannot automate these — the PAT doesn't have admin scope):

   a. **Set repo secret** (Settings → Secrets and variables → Actions →
      New repository secret):
      - Name: `CLAUDE_CODE_OAUTH_TOKEN`
      - Value: run `claude setup-token` locally to generate it.
      - (Optional) `ANTHROPIC_API_KEY` if the owner wants the API-key
        fallback path — can be left unset for OAuth-only.

   b. **Enable the PR-creation repo setting** (Settings → Actions →
      General → Workflow permissions):
      - ✅ check "Allow GitHub Actions to create and approve pull
        requests". Save.
      - This is easy to miss — without it, cycles run successfully but
        `gh pr create` silently fails and cycle branches end up
        orphaned. Pangolin raises loudly if this happens, but it's
        still a stumble. Surface it clearly.

9. **First dispatch + smoke test** (once the owner confirms steps
   8a/8b are done):
   - Actions tab → `agent-cycle` workflow → Run workflow
     (workflow_dispatch).
   - Expect ~2–3 minutes. Watch the run. If it goes red: the diagnostic
     output now includes `🔴` markers; paste the last 30 lines of the
     failing step log.
   - On green: verify a `cycle/run-...` branch + PR exist. The PR body
     must contain the `<!-- pangolin:auto -->` marker — if not, stop
     and investigate (pr-feedback will silently not trigger without it).

**Known gotchas:**

- The GH Actions log API sometimes returns 404 for step logs minutes
  after completion; retry via `curl -L -H "Authorization: Bearer
  $GH_TOKEN" .../actions/jobs/<id>/logs` or the web UI — not a pangolin
  bug.
- Software-mode tasks have a hard 180s timeout. Complex asks (big
  refactors) won't complete in one cycle — re-open the issue to
  continue.
- Pangolin's GHCR images are public; no packages:read secret is needed
  as long as you pull `@main`.

**Do not:**

- Do NOT run `pangolin init --force` against an existing wiki — it
  overwrites `wiki/SCHEMA.md` and resets `.ingest-watermark` to epoch
  (which would re-ingest everything).
- Do NOT add `CLAUDE_CODE_OAUTH_TOKEN` to `.env` if the repo's `.env`
  is not already gitignored — double-check before.
- Do NOT enable the cron schedule (the `# schedule:` lines are
  commented out in the shim) until the owner has seen at least one
  successful dispatch.

**Report back when step 7 is done** and when the smoke test (step 9)
passes. Include: the PR URL of the first successful cycle, and the
`cycle/...` branch name.

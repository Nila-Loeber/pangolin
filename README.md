<p align="center">
  <img src="pangolin.svg" alt="Pangolin" width="180"/>
</p>

<h1 align="center">Pangolin</h1>

<p align="center"><em>Your wiki's slow, secure, autonomous co-author.</em></p>

---

Pangolin drops an owner-triggered conversational loop into any Git repo —
research, ingest, think, write, self-improve, open PR, repeat. A production
implementation of Karpathy's LLM-wiki pattern, hardened for real use.

**Status: alpha.** API surface and defaults may change.

## Why Pangolin

- **Async by design.** No chat UI, no notifications, no "are you there?".
  Cycles run on dispatch or on a cron you control. You read the PRs when
  you're ready. Mental-health-friendly by construction.
- **Owner-triggered only.** No inbound webhooks, no public endpoints.
  Nothing runs unless you click dispatch or the schedule fires.
- **Secure by default.** Every agent call runs in a per-agent gVisor
  sandbox with an explicit filesystem mount set and blocked egress
  outside a pinned allowlist. No plugin registry, no tool marketplace.
- **Wiki, not chat.** Output is committed content in your repo — fragments,
  pages, drafts — reviewed via normal PRs. Git is the memory.

## Quick start

In your wiki repo:

```bash
pip install git+https://github.com/Nila-Loeber/pangolin.git@main
pangolin init
git add -A && git commit -m "feat: initialize pangolin"
git push
```

Set these **repository secrets** in GitHub (Settings → Secrets and variables
→ Actions):

- `CLAUDE_CODE_OAUTH_TOKEN` — Claude Max subscription token.
  Run `claude setup-token` locally to generate one.
- `ANTHROPIC_API_KEY` *(optional)* — API-key fallback if the OAuth path
  isn't available. Leave unset if you're using the subscription.

Enable **one repo setting** (Settings → Actions → General → Workflow
permissions): ✅ **"Allow GitHub Actions to create and approve pull
requests"**. Without this, cycles run but `gh pr create` fails with
`GitHub Actions is not permitted to create or approve pull requests` and
your cycle branches end up orphaned.

The default `GITHUB_TOKEN` provided by Actions is enough for everything else
(repo read/write, issues, GHCR image pulls — the pangolin agent images are
public).

Then dispatch `.github/workflows/agent-cycle.yml` from the **Actions** tab
(workflow_dispatch). The cycle posts a summary comment on the sentinel issue
and opens a PR with its changes when there's content to commit.

### For AI agents: installing pangolin on behalf of an owner

> If you are an AI agent reading this because an owner asked you to install
> pangolin into their wiki repo, follow these steps exactly.

1. `pip install git+https://github.com/Nila-Loeber/pangolin.git@main`; verify `pangolin version`.
2. From the wiki repo root: `pangolin init` — **not** `--force`; pass `--with-wiki` **only** if `wiki/` is empty.
3. If `.gitignore` lacks `.env` or `.venv/`, add them.
4. Ask the owner whether they want Opus for thinking/writing (package default is Sonnet). If yes, drop a `modes.override.yml` with those two fields.
5. Show the diff, then commit (`feat: initialize pangolin`) and push.
6. **Stop.** Tell the owner they must do two things manually (you cannot — PAT has no admin scope):
   - Add the `CLAUDE_CODE_OAUTH_TOKEN` repo secret (`claude setup-token` generates it).
   - Settings → Actions → General → Workflow permissions → ✅ "Allow GitHub Actions to create and approve pull requests". Without this, cycles run green but PRs never open.
7. Once confirmed: dispatch `agent-cycle` from the Actions tab. A green run produces a `cycle/run-...` branch AND a PR whose body contains `<!-- pangolin:auto -->`. If either is missing, investigate — don't declare success.

Do **not**: run `pangolin init --force` on an existing wiki (overwrites `SCHEMA.md`, resets `.ingest-watermark` to epoch); enable the commented-out cron schedule before a manual dispatch has succeeded.

## What `pangolin init` creates

| Path | Purpose |
|---|---|
| `.github/workflows/agent-cycle.yml` | Thin shim — sole source of behavior pinning (`PANGOLIN_REF`) |
| `wiki/SCHEMA.md` | Wiki structure conventions (edit freely) |
| `wiki/fragment/` | Quarantine zone for untrusted research output |
| `.ingest-watermark` | Fragment-processing cursor |
| `notes/ideas/`, `drafts/`, `content/` | Content areas (empty directories, kept via `.gitkeep`) |

Everything else — `modes.yml`, `docs/*-agent.md`, validators — lives inside
the pip package. The wiki repo never mirrors orchestration logic.

**Customizing without fork drift**: to override a package default, check a
same-named file into your wiki at the same relative path:

- `modes.override.yml` — deep-merged on top of the package `modes.yml`
  (per-mode field replacement, absent modes unchanged). Example:
  ```yaml
  modes:
    thinking: { model: claude-opus-4-7 }
    writing:  { model: claude-opus-4-7 }
  ```
- `docs/<name>.md` — replaces that specific agent-SSoT doc in full.

## Pinning behavior to a version (prod wikis)

The shim exposes one env var — `PANGOLIN_REF` — that drives BOTH the pip
install ref AND the GHCR image tag, so agent images and orchestrator code
always match.

```yaml
# .github/workflows/agent-cycle.yml
env:
  PANGOLIN_REF: main       # continuous — tracks upstream HEAD
  # PANGOLIN_REF: abc1234  # pinned — validated commit SHA
```

Typical prod flow: keep your **canary wiki** on `main`, let upstream changes
bake there, then bump your **prod wiki**'s `PANGOLIN_REF` to the SHA you've
validated.

## Commands

```
pangolin init                  # scaffold config into current repo (new wiki)
pangolin refresh-workflows     # re-sync .github/workflows/*.yml from the
                               # installed package (existing wiki, after a
                               # pip upgrade that ships a new shim)
pangolin cycle                 # workflow entry point: harden egress + run one
                               # cycle (+ one software task if queued, + one
                               # PR-feedback iteration if there's an owner
                               # comment on an open pangolin PR). The agent-
                               # cycle workflow shim calls this.
pangolin run                   # cycle only, no egress setup. Use when the
                               # proxy is already up (tests, local tinkering).
pangolin harden-egress         # start proxy + export HTTPS_PROXY only. Split
                               # out for flexibility; `pangolin cycle` is the
                               # normal entry point.
pangolin version               # print installed version
```

## Known limitations (alpha)

- **Software-mode timeout is 180s.** Complex code tasks inherently loop
  on tool-use iterations; a single cycle can't complete them. To
  continue work, comment on the open PR — the next cycle's PR-feedback
  loop picks up your comment, classifies it, and iterates on the same
  branch.
- **Log uploads from GH Actions runners can flake.** Not a pangolin bug;
  unrelated to the egress proxy. When a step goes red, the web UI
  sometimes shows the log even when the API doesn't.
- **Single-user threat model.** The sandbox is designed for *you* being
  the sole owner triggering cycles on your own repos. Shared wikis, CI
  triggers from untrusted forks, or hosted multi-tenant use cases
  require more hardening.

## Security model

- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — engineering narrative
  (assumptions → adversaries → defenses in code → known gaps).
- [docs/SECURITY_TARGET.md](docs/SECURITY_TARGET.md) — CC-style review
  artefact (assets → threats → objectives → SFRs → TSS → residuals).

TL;DR: trust gVisor + GitHub for everything, plus Anthropic's CLI to honor
`--allowedTools ""` during the research summarization step. The egress proxy
(`pangolin-egress-proxy`, mitmproxy + addon) enforces a hostname allowlist
and does MITM body inspection on `api.anthropic.com` to block server-side
tool exfil; other hosts are TLS-spliced.

## Upgrading

```bash
# Bump the installed package:
pip install --upgrade git+https://github.com/Nila-Loeber/pangolin.git@<new-ref>

# If the shim changed (new env var, new step), sync it:
pangolin refresh-workflows
git diff .github/workflows/    # review before committing
git add .github/workflows/agent-cycle.yml && git commit -m "chore: bump pangolin shim"
```

Your `modes.override.yml`, wiki content, and anything under `docs/` that you
customized are never touched by `refresh-workflows` — it only syncs
`.github/workflows/*.yml`. For a full re-scaffold (overwrites `wiki/SCHEMA.md`
and `.ingest-watermark`), use `pangolin init --force` — review diffs first.

## License

MIT — see [LICENSE](LICENSE).

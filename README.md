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
pip install git+https://github.com/Nila-Loeber/pangolin.git@v0.1
pangolin init
git add -A && git commit -m "feat: initialize pangolin"
git push
```

Set these GitHub secrets on the repo:

- `CLAUDE_CODE_OAUTH_TOKEN` — Claude Max subscription token
  (run `claude setup-token` locally to generate one)
- `ANTHROPIC_API_KEY` — optional fallback if OAuth is unset

Then dispatch `.github/workflows/agent-cycle.yml` from the Actions tab.

## What `pangolin init` creates

| Path | Purpose |
|---|---|
| `modes.yml` | Per-mode permission profiles (network, FS, tools) |
| `wiki/SCHEMA.md` | Wiki structure conventions |
| `wiki/fragment/` | Quarantine zone for untrusted research output |
| `docs/*.md` | Agent SSoT prompts (edit to customize voice/domain) |
| `.github/workflows/agent-cycle.yml` | Scheduled/dispatch-triggered cycle (also processes one software ticket per run) |
| `.ingest-watermark` | Fragment-processing cursor |
| `notes/ideas/`, `drafts/`, `content/` | Content areas |

## Commands

```
pangolin init        # scaffold config into current repo
pangolin run         # execute one cycle (+ one software task if queued)
pangolin version     # print installed version
```

## Security model

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

TL;DR: trust gVisor + GitHub for everything, plus Anthropic's CLI to honor
`--allowedTools ""` during the research summarization step.

## Upgrading

```bash
# In your wiki repo's workflow:
pip install --upgrade git+https://github.com/Nila-Loeber/pangolin.git@v0.2

# Or pin to a specific tag:
pip install git+https://github.com/Nila-Loeber/pangolin.git@v0.1.3
```

Defaults in your repo's `modes.yml`, `docs/`, `wiki/SCHEMA.md`, and workflow
files are **not** overwritten on upgrade. Compare them to the new defaults:

```bash
pangolin init --force  # overwrite (destructive — review diffs first)
```

## License

MIT — see [LICENSE](LICENSE).

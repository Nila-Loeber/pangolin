# Sandburg

Owner-triggered conversational cycles for wiki repositories. Drops an
autonomous research/thinking/writing loop into any Git repo, sandboxed by
gVisor + explicit bind-mounts.

**Status: alpha.** API surface and defaults may change.

## Quick start

In your wiki repo:

```bash
pip install git+https://github.com/Nila-Loeber/sandburg.git@v0.1
sandburg init
git add -A && git commit -m "feat: initialize sandburg"
git push
```

Set these GitHub secrets on the repo:

- `CLAUDE_CODE_OAUTH_TOKEN` — Claude Max subscription token
  (run `claude setup-token` locally to generate one)
- `ANTHROPIC_API_KEY` — optional fallback if OAuth is unset

Then dispatch `.github/workflows/agent-cycle.yml` from the Actions tab.

## What `sandburg init` creates

| Path | Purpose |
|---|---|
| `modes.yml` | Per-mode permission profiles (network, FS, tools) |
| `wiki/SCHEMA.md` | Wiki structure conventions |
| `wiki/fragment/` | Quarantine zone for untrusted research output |
| `docs/*.md` | Agent SSoT prompts (edit to customize voice/domain) |
| `.github/workflows/agent-cycle.yml` | Scheduled/dispatch-triggered cycle |
| `.github/workflows/agent-software.yml` | Per-ticket software-task runner |
| `.ingest-watermark` | Fragment-processing cursor |
| `notes/ideas/`, `drafts/`, `content/` | Content areas |

## Commands

```
sandburg init        # scaffold config into current repo
sandburg run         # execute one cycle
sandburg software    # execute one software-mode task
sandburg version     # print installed version
```

## Security model

See [THREAT_MODEL.md](https://github.com/Nila-Loeber/sandburg/blob/main/docs/THREAT_MODEL.md).

TL;DR: trust gVisor + GitHub for everything except the research summarization
step, where you additionally trust Anthropic's CLI to honor `--allowedTools ""`.

## Upgrading

```bash
# In your wiki repo's workflow:
pip install --upgrade git+https://github.com/Nila-Loeber/sandburg.git@v0.2

# Or pin to a specific tag:
pip install git+https://github.com/Nila-Loeber/sandburg.git@v0.1.3
```

Defaults in your repo's `modes.yml`, `docs/`, `wiki/SCHEMA.md`, and workflow
files are **not** overwritten on upgrade. Compare them to the new defaults:

```bash
sandburg init --force  # overwrite (destructive — review diffs first)
```

## License

MIT

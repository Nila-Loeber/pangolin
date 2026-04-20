# CLAUDE.md — pangolin dev notes

Pangolin is an owner-triggered conversational-loop CLI for wiki repos: research → ingest → think → write → self-improve → PR, on dispatch or cron. Single-user, alpha (v0.1).

## Local dev loop

```bash
pip install -e ".[dev]"        # editable install + pytest, ruff, build
python3 -m pytest tests/ -v    # 38 security tests, runs in <1s
ruff check src/ tests/         # current baseline has style noise. Not a regression gate.
```

The `tests/test_security.py` suite is the single source of truth for the security model — every invariant is asserted there. If you change `modes.yml`, `tools.py`, `orchestrate.py` security paths, or any `trust_level`/`quarantine_output`/`allowed_tools` logic, run pytest before pushing.

## Layout

- `src/pangolin/` — package code
  - `cli.py` — `pangolin init|run|version` entry
  - `orchestrate.py` — cycle pipeline, `CycleRunner`, container spawn, gh integration, proxy sidecar lifecycle
  - `tools.py` — `ToolExecutor`, FS scope enforcement (API-key fallback path uses `pangolin-agent-bash` for sandboxed `Bash`)
  - `modes.py` — modes.yml loader + invariant validator + JSON schemas for direct-mode agents
  - `providers.py` — anthropic SDK wrapper (in-process API-key path)
  - `software.py` — software-task-per-cycle pickup (OAuth → `pangolin-agent-software` via CLI, or API-key → in-process SDK)
  - `scaffold.py` — `pangolin init` implementation
  - `default_config/` — files copied into wiki repos by `init`
- `tests/test_security.py` — the security regression suite (SFR-* tagged)
- `Containerfile.bash` → `pangolin-agent-bash` (Python+bash, no network — used by tools.py for the API-key fallback)
- `Containerfile.llm` → `pangolin-agent-llm` (Node+claude-CLI, no bash — default for all non-software modes under OAuth)
- `Containerfile.software` → `pangolin-agent-software` (Node+claude-CLI+bash — software-mode only, under OAuth)
- `Containerfile.egress` → `pangolin-egress-proxy` (squid, two-port hostname allowlist — sidecar for all agent outbound)
- `.github/workflows/build-agent-images.yml` — publishes all four to GHCR

## The four images (three agent + one infra)

| Image | Who uses it | Why |
|---|---|---|
| `pangolin-agent-llm` | all non-software modes (OAuth path) | Node + CLI, no bash → defense-in-depth floor when `--allowedTools` is strict |
| `pangolin-agent-software` | software mode (OAuth path) | Node + CLI + bash → CLI can fork bash for code tasks |
| `pangolin-agent-bash` | Bash tool via `tools.py` (API-key fallback path) | bash + no network → sandboxed shell for the in-process SDK route |
| `pangolin-egress-proxy` | sidecar, used by all agent containers | squid forward proxy, hostname allowlist, two trust tiers (tight + loose) |

## Egress filtering

`orchestrate._ensure_proxy_running()` starts `pangolin-egress-proxy` on the `pangolin-net` docker network at cycle start. All agent containers get `HTTPS_PROXY=http://<proxy-ip>:31XX` injected into their env (via `_base_docker_flags`). Proxy IP (not hostname) because gVisor doesn't reliably resolve Docker's embedded DNS.

Two ports:
- **3128 tight** — `api.anthropic.com`, `api.github.com`, `github.com`, `ghcr.io`, `pypi.org`, `files.pythonhosted.org`, `gvisor.dev`, `storage.googleapis.com`, `dl-cdn.alpinelinux.org`, `registry.npmjs.org`. Default for all modes.
- **3129 loose** — any HTTPS host. Used **only** by research-search (WebFetch is client-side and needs arbitrary web reach).

MITM (ssl-bump for token-injection + ICAP for request-body tool-allowlist) is a planned follow-up. See BACKLOG "MITM the egress proxy".

## Direct (json-schema) modes — post-Q1

All knowledge-work modes have moved off container tool-use to direct json-schema. The agent returns structured JSON; the host writes files with path-scope validation. Faster (one roundtrip), deterministic (no agent-claims-write-but-didn't), and smaller attack surface (no outbound tools).

- **writing** → schema `writing` → `_run_writing_direct` → `_execute_writing_drafts`
- **thinking** → schema `thinking` → `_run_thinking_direct` → `_apply_path_scoped_writes`
- **wiki-ingest** phase → schema `wiki-ingest` → direct in `_phase_wiki_ingest` → `_apply_path_scoped_writes`
- **research-summarise** → schema `research` (unchanged)
- **triage**, **summary**, **self-improve**, **wiki-index** → direct (unchanged)

Only **software** remains container tool-use (inherent — needs iterative bash + code edits).

## modes.yml invariants

Enforced by `modes.py::_validate_invariants` and tested in `test_security.py::TestModesConsistency`:
- `trust_level: untrusted` → `code_execution: false` AND `quarantine_output` set
- `readable_paths` and `writable_paths` non-empty
- `writable_paths ⊆ readable_paths`
- Direct (json-schema) modes: `allowed_tools: []` (no tools)
- Container tool-use modes: `--allowedTools` whitelist enforced at CLI level, mounts enforced at OS level

## Local cycle testing

Local-testable without any external state:
- `pytest tests/` (security invariants)
- `pangolin init` against a tmp dir (scaffolding correctness)
- `docker build -f Containerfile.{bash,llm,software,egress} ...` (image-build correctness)

End-to-end requires real GH + Anthropic:
- `GH_TOKEN` + `CLAUDE_CODE_OAUTH_TOKEN` in env
- Run from `/mnt/sandcastle/pangolin/test-pangolin/` → creates issues + PRs in `Nila-Loeber/test-pangolin`
- Proxy + agent containers auto-start via `_ensure_proxy_running`; no manual docker setup

## Auth in this sandcastle

- `/mnt/sandcastle/pangolin/.env` (gitignored, mode 600) holds `GH_TOKEN` + `CLAUDE_CODE_OAUTH_TOKEN`. Source: `set -a && . /mnt/sandcastle/pangolin/.env && set +a`
- Per-repo git credential helper pulls `GH_TOKEN` from env at push time
- Remotes are HTTPS
- `ANTHROPIC_API_KEY` unset (we use OAuth; API-key fallback path is exercised only if you explicitly set it)

## Don't-touch areas (single-source-of-truth)

- Anything in `default_config/` is the template shipped via `init`. Changes propagate to every new wiki on `pangolin init`.
- `test-pangolin/` has its own copies (doesn't auto-update on package upgrade). If you change `default_config/workflows/agent-cycle.yml`, `default_config/modes.yml`, or `default_config/docs/*.md`, also update the copy in `test-pangolin/` for the canary to stay in sync.

## BACKLOG.md

Canonical pre-GA list. Check it before inventing work. Current high-level items:

1. Egress filter self-hosting (partial — proxy done, iptables host-level step still pending; workflow templates still use Harden-Runner)
2. Image reproducibility (apk pin rot, digest-pinning)
3. MITM the egress proxy (ssl-bump for token injection + ICAP for tool-allowlist body filter)
4. Generalize nlkw's wiki conventions

Software-mode timeout on complex Opus code tasks is a known limitation — the tool-use iteration inherently exceeds 180s. Considered fixes: switch software to Sonnet (faster but lower quality); accept that owner re-opens to continue work.

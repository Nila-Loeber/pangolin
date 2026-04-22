# CLAUDE.md — pangolin dev notes

Pangolin is an owner-triggered conversational-loop CLI for wiki repos: research → ingest → think → write → self-improve → PR, on dispatch or cron. Single-user, alpha (v0.1).

## Local dev loop

```bash
pip install -e ".[dev]"        # editable install + pytest, ruff, build
python3 -m pytest tests/ -v    # full suite, runs in <1s
ruff check src/ tests/         # current baseline has style noise. Not a regression gate.
```

The `tests/test_security.py` suite is the single source of truth for the security model — every invariant is asserted there. If you change `modes.yml`, `tools.py`, `orchestrate.py` security paths, or any `trust_level`/`quarantine_output`/`allowed_tools` logic, run pytest before pushing.

## Layout

- `src/pangolin/` — package code
  - `cli.py` — `pangolin init|run|harden-egress|version` entry
  - `orchestrate.py` — cycle pipeline, `CycleRunner`, container spawn, gh integration, proxy sidecar lifecycle
  - `tools.py` — `ToolExecutor`, FS scope enforcement (API-key fallback path uses `pangolin-agent-bash` for sandboxed `Bash`)
  - `modes.py` — modes.yml loader + invariant validator + JSON schemas for direct-mode agents
  - `providers.py` — anthropic SDK wrapper (in-process API-key path)
  - `software.py` — software-task-per-cycle pickup (OAuth → `pangolin-agent-software` via CLI, or API-key → in-process SDK)
  - `pr_feedback.py` — PR-feedback loop: picks up owner-authored comments on pangolin-authored open PRs and runs software-mode against the existing branch
  - `scaffold.py` — `pangolin init` implementation
  - `default_config/` — runtime SSoT for modes/docs/validator/workflow shim.
    Loaded via `paths.resolve_config()`; only the workflow shim + wiki
    seed files are copied into new wiki repos by `init`.
- `tests/test_security.py` — the security regression suite (SFR-* tagged)
- `Containerfile.bash` → `pangolin-agent-bash` (Python+bash, no network — used by tools.py for the API-key fallback)
- `Containerfile.llm` → `pangolin-agent-llm` (Node+claude-CLI, no bash — default for all non-software modes under OAuth)
- `Containerfile.software` → `pangolin-agent-software` (Node+claude-CLI+bash — software-mode only, under OAuth)
- `Containerfile.egress` → `pangolin-egress-proxy` (mitmproxy + addon, two-port hostname allowlist — sidecar for all agent outbound)
- `.github/workflows/build-agent-images.yml` — publishes all four to GHCR

## The four images (three agent + one infra)

| Image | Who uses it | Why |
|---|---|---|
| `pangolin-agent-llm` | all non-software modes (OAuth path) | Node + CLI, no bash → defense-in-depth floor when `--allowedTools` is strict |
| `pangolin-agent-software` | software mode (OAuth path) | Node + CLI + bash → CLI can fork bash for code tasks |
| `pangolin-agent-bash` | Bash tool via `tools.py` (API-key fallback path) | bash + no network → sandboxed shell for the in-process SDK route |
| `pangolin-egress-proxy` | sidecar, used by all agent containers | mitmproxy + `pangolin_egress.py` addon; hostname allowlist, two trust tiers (tight + loose), selective MITM of `api.anthropic.com` only |

## Egress filtering

`orchestrate._ensure_proxy_running()` starts `pangolin-egress-proxy` on the `pangolin-net` docker network at cycle start. All agent containers get `HTTPS_PROXY=http://<proxy-ip>:31XX` injected into their env (via `_base_docker_flags`). Proxy IP (not hostname) because gVisor doesn't reliably resolve Docker's embedded DNS.

Two ports:
- **3128 tight** — `api.anthropic.com`, `api.github.com`, `github.com`, `ghcr.io`, `pypi.org`, `files.pythonhosted.org`, `gvisor.dev`, `storage.googleapis.com`, `dl-cdn.alpinelinux.org`, `registry.npmjs.org`. Default for all modes.
- **3129 loose** — any HTTPS host. Used **only** by research-search (WebFetch is client-side and needs arbitrary web reach).

Phase A+B both live, implemented in one mitmproxy addon at
`src/pangolin/pangolin_egress.py` (no squid, no ICAP, no side-process
aiohttp). At startup the proxy generates a runtime CA (rotates each
cycle) and writes the public cert to a shared volume `pangolin-proxy-ca`,
which every agent container mounts read-only at
`/etc/pangolin/proxy-ca.crt`. `NODE_EXTRA_CA_CERTS=/etc/pangolin/proxy-ca.crt`
(baked into Containerfile.llm + Containerfile.software) makes the
claude CLI trust it.

A `tls_clienthello` hook splices every TLS connection *except*
`api.anthropic.com` (via `ignore_connection=True`) — so the host `gh`
CLI and other allowlisted clients don't need to trust our CA. Only
Anthropic gets MITM'd.

**Phase A — token hiding**: the real `CLAUDE_CODE_OAUTH_TOKEN` never
enters an agent container. It rides into the proxy's env as
`ANTHROPIC_TOKEN`; the addon's `request` hook strips any incoming
Authorization header and injects `Bearer <token>` for
`api.anthropic.com`. Agents ship a fixed placeholder so the CLI
doesn't short-circuit. Closes the `/proc/self/environ` +
prompt-injected-Bash exfil path.

**Phase B — endpoint allowlist + server-side-tool block**: the addon
restricts `api.anthropic.com` at two levels. First,
`ANTHROPIC_ENDPOINT_ALLOWLIST` — currently `{("POST", "/v1/messages")}`
— is checked *before* the Authorization rewrite, so denied endpoints
(batches, count_tokens, future beta paths, org-scoped routes) get a
403 without ever bearing the real OAuth token upstream. Second, every
allowlisted request body is parsed and any tool entry with a `type`
field rejected — Anthropic's server-side tools (`web_fetch`,
`web_search`, `code_execution`, ...) that a compromised agent could
use to exfil data *through* api.anthropic.com to an attacker-chosen
URL. Custom tools (`{name, description, input_schema}`) pass through.
The allowlist (`SERVER_TOOL_ALLOWLIST`) starts empty — no pangolin
mode needs server-side tools today; research phase 1 uses the CLI's
client-side WebSearch/WebFetch, not the API's.

## Direct (json-schema) modes — post-Q1

All knowledge-work modes have moved off container tool-use to direct json-schema. The agent returns structured JSON; the host writes files with path-scope validation. Faster (one roundtrip), deterministic (no agent-claims-write-but-didn't), and smaller attack surface (no outbound tools).

- **writing** → schema `writing` → `_run_writing_direct` → `_execute_writing_drafts`
- **thinking** → schema `thinking` → `_run_thinking_direct` → `_apply_path_scoped_writes`
- **wiki-ingest** phase → schema `wiki-ingest` → direct in `_phase_wiki_ingest` → `_apply_path_scoped_writes`
- **research-summarise** → schema `research` (unchanged)
- **triage**, **summary**, **self-improve**, **wiki-index** → direct (unchanged)

Only **software** remains container tool-use (inherent — needs iterative bash + code edits).

## PR-feedback loop

After the main cycle + software-task pickup, `pr_feedback.run()` closes
the conversational loop on PRs. For every open pangolin-authored PR
(matched by `AGENT_MARKER` in the body), it reads comments newer than
the latest cycle-agent commit on the branch — the watermark. Owner-
authored ones (strict per-comment `_is_owner_comment`) get fed to
software-mode with a DATA-not-instructions preamble; the agent commits
on the same branch. One comment per cycle, oldest first. Inference
filter: a progress reply + push only happens if a new diff was actually
produced. Self-loop guard: our progress reply carries `AGENT_MARKER`
and is therefore invisible to the next cycle's watermark filter.

No label, no magic keyword — a fresh owner comment on a pangolin PR is
the trigger. Phase 2 work (not yet): inline review-thread comments and
GraphQL thread resolution.

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

## Atomic deploy (package is SSoT)

Behavior lives in the pip package, not in the wiki repo. Wiki repos only
check in the thin workflow shim + user content. `pip install pangolin@X`
at cycle start is the deploy mechanism — bumping the pinned ref in the
shim (or leaving it on `@main`) updates every wiki atomically.

- `modes.yml`, `docs/*-agent.md`, `validate_output.sh`, `workflows/agent-cycle.yml`:
  live in `src/pangolin/default_config/` and are loaded at runtime via
  `paths.resolve_config(<relpath>)`.
- Wiki override mechanism: drop a same-named file at the same relative
  path in the wiki repo — it wins over the package default.
  - `<wiki>/modes.override.yml` → deep-merged into package `modes.yml`
    (per-mode field replacement, absent modes unchanged).
  - `<wiki>/docs/<name>.md` → replaces that specific ssot doc.
- `test-pangolin/` only holds the workflow shim + its own wiki content.
  After a package change, the canary updates on the next `workflow_dispatch`;
  no manual sync.

## BACKLOG.md

Canonical pre-GA list. Check it before inventing work. Current high-level items:

1. Image reproducibility (apk pin rot, digest-pinning)
2. Generalize nlkw's wiki conventions

Done (moved out of BACKLOG):
- Egress proxy rewrite — squid+ICAP+aiohttp replaced by a single
  mitmproxy addon (`src/pangolin/pangolin_egress.py`). Phase A (token
  hiding via Authorization rewrite) and Phase B (body inspection,
  server-side-tool block) both live in the same addon; non-Anthropic
  hosts are TLS-spliced so the host `gh` CLI doesn't need our CA.
- MITM Phase B — validates `/v1/messages` request bodies; rejects
  server-side tool types (web_fetch, web_search, code_execution, ...).
  Closes the `api.anthropic.com`-as-exfil vector.
- MITM Phase A — MITM for api.anthropic.com, runtime CA in shared
  volume, Authorization header stripped + re-injected server-side. Real
  OAuth token no longer reaches any agent container.
- Atomic deploy — package is SSoT; wiki repos only hold the workflow shim
  + user content. `modes.yml` + `docs/*-agent.md` loaded from the installed
  package via `paths.resolve_config()`; wiki can override per-file.
  `pangolin harden-egress` CLI subcommand moved iptables/proxy out of yml.
- Self-hosted egress filter — `pangolin-egress-proxy` sidecar + iptables
  replaced `step-security/harden-runner`. Per-mode `egress: tight|loose`
  field in `modes.yml` drives port selection.
- Agent container merge — decided to keep split (bash vs llm).

Software-mode timeout on complex Opus code tasks is a known limitation — the tool-use iteration can exceed the 480s budget on anything larger than a mid-size change. Continuation flow: the Owner comments on the open PR (not re-opens the issue); the next cycle's `pr_feedback.run()` picks up the comment, classifies it, and iterates on the same branch. Considered fallbacks: switch software to Sonnet (faster but lower quality).

# CLAUDE.md — pangolin dev notes

Pangolin is an owner-triggered conversational-loop CLI for wiki repos: research → ingest → think → write → self-improve → PR, on dispatch or cron. Single-user, alpha (v0.1).

## Local dev loop

```bash
pip install -e ".[dev]"        # editable install + pytest, ruff, build
python3 -m pytest tests/ -v    # 38 security tests, runs in <1s
ruff check src/ tests/         # current baseline has style noise (~50 hits, mostly compact one-liners + unused imports). Not a regression gate.
```

The `tests/test_security.py` suite is the single source of truth for the security model — every invariant is asserted there. If you change `modes.yml`, `tools.py`, `orchestrate.py` security paths, or any `trust_level`/`quarantine_output`/`allowed_tools` logic, run pytest before pushing.

## Layout

- `src/pangolin/` — package code
  - `cli.py` — `pangolin init|run|version` entry
  - `orchestrate.py` (~1500 LOC) — the cycle pipeline, `CycleRunner`, container spawn, gh integration
  - `tools.py` — `ToolExecutor`, FS scope enforcement, container image name
  - `modes.py` — modes.yml loader + invariant validator
  - `providers.py` — anthropic + scaleway provider abstraction
  - `software.py` — software-task-per-cycle pickup
  - `scaffold.py` — `pangolin init` implementation
  - `default_config/` — files copied into wiki repos by `init`
- `tests/test_security.py` — the security regression suite (SFR-* tagged)
- `Containerfile.bash` → builds `pangolin-agent-bash` (no network, hosts Bash tool)
- `Containerfile.llm` → builds `pangolin-agent-llm` (network only to api.anthropic.com, wraps every LLM call)
- `.github/workflows/build-agent-images.yml` — pushes both to GHCR on Containerfile changes

## Two agent images (decided: keep split, do not merge)

`pangolin-agent-bash` and `pangolin-agent-llm` are kept separate as defense-in-depth: bash exec doesn't get network, LLM call doesn't get bash. See git history for the merge-or-not decision. If you ever reconsider, the cost is documented in commit `3121916`.

## modes.yml invariants

Enforced by `modes.py::_validate_invariants` and tested in `test_security.py::TestModesConsistency`:
- `trust_level: untrusted` → `code_execution: false` AND `quarantine_output` set
- `readable_paths` and `writable_paths` non-empty
- `writable_paths ⊆ readable_paths`
- Direct (json-schema) modes: `allowed_tools: []`, no container needed
- Container modes: tooluse via `--allowedTools` to the claude CLI in `pangolin-agent-llm`

## Local cycle testing

The full `pangolin run` cycle calls real GH (`gh issue list`, creates sentinel issues, opens PRs) and real Anthropic (every mode call). It is **not** a pure local test. The pieces that ARE local-testable:

- `pytest` (security invariants)
- `pangolin init` against a tmp dir (scaffolding correctness)
- `docker build -f Containerfile.bash -t pangolin-agent-bash:latest .` and same for `.llm` (image-build correctness)
- `python3 -c "from pangolin import orchestrate; orchestrate.precheck()"` requires `GH_TOKEN` + repo context but doesn't make LLM calls

For an end-to-end test, run `pangolin run` from inside `/mnt/sandcastle/pangolin/test-pangolin/` with `GH_TOKEN` and `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) in env. This will create real issues and PRs in `Nila-Loeber/test-pangolin`.

## Auth in this sandcastle

- `GH_TOKEN` lives in `/mnt/sandcastle/pangolin/.env` (gitignored, mode 600). Source it: `set -a && . /mnt/sandcastle/pangolin/.env && set +a`.
- Per-repo git credential helper in both repos pulls `GH_TOKEN` from env at push time. Source `.env` once per shell, `git push` works.
- Remotes are HTTPS (switched from SSH because no SSH keys in sandcastle).
- `CLAUDE_CODE_OAUTH_TOKEN` is **not** in `.env` — only set when actually running `pangolin run` end-to-end.

## Don't-touch areas (single-source-of-truth)

- Anything in `default_config/` is the template that ships into wiki repos via `init`. Changes here propagate to every new wiki on `pangolin init`.
- Existing wiki repos (e.g. `test-pangolin`) have their own copies — they don't auto-update on package upgrade. If you change `default_config/workflows/agent-cycle.yml`, also update the copy in `test-pangolin/.github/workflows/agent-cycle.yml` for the canary to stay in sync.

## BACKLOG.md

Canonical pre-GA list. 4 items currently:
1. Self-host the egress filter (drop StepSecurity dependency for private repos)
2. Image reproducibility (apk pin rot, switch to digest-pinned + dependabot)
3. Generalize nlkw's wiki conventions (extract presets)
4. (deleted: agent container merge — decision made to keep split)

Pick from this list before inventing new work.

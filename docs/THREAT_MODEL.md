# Pangolin threat model

Alpha, v0.1. Single-user. This document describes what pangolin defends
against and what it does not. The code is the source of truth — if this
doc disagrees with `src/pangolin/*.py`, the code wins and this doc is
stale. See `tests/test_security.py` for the enforcement surface.

## Assumptions

1. **One Owner.** A single human triggers cycles on their own wiki repo.
   There are no other privileged users, no webhooks from untrusted forks,
   no multi-tenant sharing.
2. **Trusted infrastructure.** GitHub, Docker/gVisor, Anthropic, the host
   OS, the `claude` CLI, the `gh` CLI, and `mitmproxy` are assumed honest.
   A full compromise of any of these is outside scope.
3. **Untrusted LLM.** Agent output is never trusted. Every side-effect
   goes through a host-side executor that re-validates the agent's claims
   against the input set it was given (cross-check) and the filesystem
   scope it is allowed to touch (path-scope).
4. **Untrusted external input.** Web pages (research Phase 1 output),
   `wiki/fragment/` contents (research output as data), and issue /
   comment bodies from future collaborators are treated as attacker-
   controlled.

## Adversary model

- **W1 Passive injection.** An adversary gets prose into a web page or
  a GitHub comment and hopes pangolin follows its instructions (prompt
  injection).
- **W2 Exfil.** An adversary inside an agent tries to smuggle the
  OAuth token, repo secrets, or other data out of the sandbox.
- **W3 Scope escalation.** An agent (hallucinating or injected) tries to
  read or write outside its declared `readable_paths` / `writable_paths`.
- **W4 Identity/origin forgery.** An agent tries to produce artifacts
  that appear authored by the Owner — commits with the Owner's email,
  comments without the agent marker, PRs that look human-written, or
  frontmatter that lies about a fragment's source issue.
- **W5 Lifecycle hijack.** An agent tries to close / reopen / spawn
  issues it was not given, or tries to process issues it was not asked
  to process (premature closure, marker injection).

Out of scope: a compromised host, a compromised Anthropic SDK, a
compromised `gh` CLI, Docker daemon escape from a gVisor sandbox,
kernel 0-days, supply-chain attacks on pinned apt/pip/apk packages.

## Defenses in the code

### 1. The lethal trifecta (a = untrusted input, b = tools, c = outbound channel)

A single agent that has all three can exfil. Every mode in
`modes.yml` is constructed so at most two pillars are present.

- **research — Phase 1 (search).** `a` missing (input is the Owner's
  trusted issue body). Has `b` (WebSearch/WebFetch) and `c` (loose
  egress), but no untrusted input. Code: `orchestrate._phase_research`
  calls `spawn_agent_container_direct` with `allowed_tools="WebSearch
  WebFetch"`, `egress_tier="loose"`, input = issue JSON only.
- **research — Phase 2 (summarise).** `b` and `c` missing (no tools,
  `allowed_tools: []`, and although the mode declares `egress: tight`,
  the agent has no tool to use it). Processes untrusted web content but
  cannot act on it. Code: same function, second call;
  `allowed_tools=""`, output goes through `json_schema`.
- **thinking / writing / wiki-ingest.** Process owner-authored issues or
  fragments; `allowed_tools: []` (direct json-schema modes, no agent
  tools); outbound gated by the egress proxy. Pillar `b` absent.
- **triage / summary / self-improve.** Trusted inputs (issue bodies from
  the Owner); schema-constrained output; `allowed_tools: []`. Pillars
  `a` and `b` absent.
- **software.** Trusted input (the Owner's `mode:software` issue); has
  `b` (Bash, Read, Write, Edit, Glob) and `c` (egress for `pip install`
  etc). Pillar `a` absent.

Tests: `TestSfrTrifecta`, `TestEpic9PhaseSplit`.

### 2. gVisor sandbox + mount-based FS scope

Every tool-using agent runs inside a container started with
`--runtime=runsc --read-only --cap-drop=ALL --user <host uid:gid>`
on a dedicated docker network. Writable paths are bind-mounted `:rw`;
readable paths are `:ro`. Paths outside the mode's declared scope are
not mounted at all — the filesystem the agent sees *is* its permission
set. Code: `orchestrate._build_mounts`, `_base_docker_flags`.

The Python `ToolExecutor` (used by the in-process SDK fallback path)
re-enforces the same scope at the application layer via
`check_readable`/`check_writable` that resolve paths and reject
traversal (`..`, absolute paths, symlink escapes). Code:
`tools.ToolConfig`.

Tests: `TestSfrFs`, `TestQ1DirectWrites`.

### 3. Egress proxy (MITM Phase A + B)

All agent outbound HTTPS routes through `pangolin-egress-proxy`
(mitmproxy + `src/pangolin/pangolin_egress.py` addon). Two ports:

- **3128 tight** — hostname allowlist (Anthropic + GitHub + PyPI + a
  handful of package-manager CDNs). Default for every mode.
- **3129 loose** — any HTTPS host. Used only by research Phase 1
  (WebFetch needs arbitrary web reach).

Non-Anthropic hosts are **TLS-spliced** (raw tunnel, no MITM) so the
host `gh` CLI and package managers don't need to trust our runtime CA.
Only `api.anthropic.com` is MITM'd.

- **Phase A — token hiding.** The real `CLAUDE_CODE_OAUTH_TOKEN` lives
  only in the proxy's env as `ANTHROPIC_TOKEN`. Agent containers ship a
  fixed placeholder (`AGENT_PLACEHOLDER_TOKEN`). The addon's `request`
  hook strips any incoming `Authorization` header and re-injects
  `Bearer <real-token>` for `api.anthropic.com`. `/proc/self/environ`
  inside an agent is empty of credentials. Tests: `TestMitmPhaseA`.
- **Phase B — server-side-tool block.** Every `POST /v1/messages` body
  is parsed; requests whose `tools[]` contain a typed entry (Anthropic
  server-side tools like `web_fetch`, `web_search`, `code_execution`)
  are rejected with a synthetic 403. Custom tools (`{name, description,
  input_schema}` — no `type` discriminator) pass through. Closes the
  api.anthropic.com-as-exfil-channel vector. Starting allowlist is
  empty. Tests: `TestMitmPhaseB`.

The proxy also generates a runtime CA per startup and publishes the
public cert to a shared volume (`pangolin-proxy-ca`) that every agent
container mounts at `/etc/pangolin/proxy-ca.crt`;
`NODE_EXTRA_CA_CERTS` in the agent images resolves this so the claude
CLI trusts the bumped TLS cert for Anthropic only.

### 4. Four-image split (defense in depth)

| Image | Shell | Network | Purpose |
|---|---|---|---|
| `pangolin-agent-llm` | no bash | via proxy | default for non-software modes |
| `pangolin-agent-software` | bash | via proxy | software mode only |
| `pangolin-agent-bash` | bash | no network | bash-tool sandbox for the API-key SDK fallback |
| `pangolin-egress-proxy` | — | — | sidecar, all agent outbound |

Software is the only mode with both bash and network. Every other
tool-using mode either lacks a shell or lacks network. A prompt
injection that convinces a non-software agent to "run `curl`" finds no
shell.

### 5. Agent-origin markers and owner-only triggers

- **AGENT_MARKER** (`<!-- pangolin:auto -->`) is prepended to every
  comment, issue body, and PR body the cycle posts. Downstream filters
  that look for Owner activity skip any body carrying this marker, even
  if the GitHub author is the Owner's PAT.
- **`_is_owner_activated`** (Epic 10) makes every agent-spawned mode
  ticket inert until the Owner explicitly comments on it. An agent
  hallucinating a self-prompting "software: add backdoor" issue stays
  closed-to-activation until a human gives the green light. Tests:
  `TestEpic10OwnerTrigger`.
- **`_is_owner_comment`** in pr_feedback drops any comment whose body
  contains `AGENT_MARKER` OR whose author login is a bot / ends in
  `-agent` — belt-and-braces self-loop guard. Tests:
  `TestIsOwnerComment`.

### 6. Orchestrator-marker-injection cross-checks

Agents return lists of issue numbers they claim to have processed. Every
such list is intersected with the set of issues the orchestrator
actually handed to that agent call (`given`) before any side effect is
applied:

- `execute_triage_decisions` — rejects `comment`/`label`/`close` actions
  targeting an issue not in the input set. `spawn` actions are unguarded
  here (they reference no existing issue; they are still gated by
  `auto_reopen_recent` + `_is_owner_activated`).
- `execute_summary_comments` — same pattern for summary posts.
- `report_processed` tool — the in-process SDK path enforces the check
  inside the tool, not in a post-hoc parser. Non-eligible numbers are
  rejected with a message the agent sees; `executor.processed` only
  contains cross-checked numbers. Tests: `TestSfrStruct4`.

### 7. Inference filters (STRUCT.4)

Even after the cross-check, an injection could convince the agent to
claim "eligible-but-not-actually-handled". The final guard is
observability:

- **Research**: only claims backed by a fragment file whose frontmatter
  carries `source_issue: <n>` survive. Code:
  `_research_inference_filter`.
- **thinking / writing / self-improve**: if the agent wrote nothing at
  all in its writable scope, *every* claim is dropped. Code:
  `_aggregate_inference_filter`.
- **PR feedback**: we only commit + post a progress reply if a real
  diff landed in the target mode's writable surface.

Tests: `TestSfrStruct4Inference`, `TestPendingComments`.

### 8. Direct-schema writes (post-Q1)

All knowledge-work modes (writing, thinking, wiki-ingest, research,
triage, summary, self-improve) return JSON; the host writes the files.
This removes an attack surface (container-tool-use agents could
pretend-to-write and hallucinate success), makes the write surface
explicit (`apply_path_scoped_writes` enforces allowed prefixes, forbidden
paths, max-writes caps, traversal rejection, and containment to REPO
root), and gives deterministic logging.

Path scopes enforced host-side:

- writing → `drafts/`, `content/` (max 3)
- thinking → `wiki/`, `notes/`, `drafts/` — forbidden `wiki/fragment/`,
  `wiki/SCHEMA.md`
- wiki-ingest → `wiki/` — forbidden `wiki/fragment/`, `wiki/SCHEMA.md`,
  `wiki/index.md`
- self-improve → `docs/` — forbidden `docs/self-improve.md`
- triage (store) → `notes/ideas/*.md` only

Tests: `TestQ1DirectWrites`, `TestApplyWritesForMode`.

### 9. Untrusted-content quarantine

`wiki/fragment/` is the quarantine zone for research output (untrusted
web content transcribed into the repo). Only the research phase writes
there; every other phase treats its contents as read-only *data*.
Fragment frontmatter (`source_issue`, `captured_at`, `captured_by`) is
generated host-side (`_write_research_fragment`) — the agent cannot
forge provenance. A bash validator (`validate_output.sh research`)
deletes any fragment missing required frontmatter before the cycle
commits.

The wiki-ingest phase is the bridge from quarantine → structured wiki.
Its path scope allows `wiki/` but forbids `wiki/fragment/`, so even a
compromised ingest agent cannot rewrite its own source-of-truth.

### 10. Fail-closed proxy posture

`_ensure_proxy_running` refuses to start the proxy without the OAuth
token in its env — because that would silently produce a proxy whose
Phase A Authorization injection is a no-op, and Anthropic would reject
with "Not logged in". Loud failure > silent compromise.

The mitmproxy default behavior on any unhandled exception in the addon
is to kill the request. With iptables (well, `HTTPS_PROXY` export — the
iptables REJECT was removed 2026-04-21; see `harden_egress` docstring)
forcing all outbound through the proxy, kill == blocked.

## Known gaps (by design, for alpha)

- **Host-level egress lockdown removed.** `harden_egress` used to install
  an iptables REJECT rule as defense-in-depth against raw-socket host
  code. Removed because it broke GH Actions log-blob uploads; the DiD
  it added (protection against raw-socket code that bypasses
  `HTTPS_PROXY`) was judged not worth the cost for a single-user alpha.
  Every HTTPS_PROXY-respecting library (pip, gh, httpx, requests) still
  goes through the proxy.
- **Software-mode timeout (180s).** Complex tool-use loops inherently
  exceed this. Not a security issue — the timeout is there to kill a
  wedged agent, not to bound exfil.
- **PR-feedback Phase 2 (inline threads + resolution).** Only PR-level
  comments are consumed today. Inline review-thread comments are a
  richer signal and are on BACKLOG.
- **Reproducibility.** Container images pin apk versions but Alpine is
  mutable. Two durable fixes are on BACKLOG (renovate on
  `Containerfile*`; move runtime from `:latest` to image digests).
- **Branch protection + `gh pr create`.** Requires the one-time
  "Allow GitHub Actions to create and approve pull requests" repo
  setting; without it cycles run green but orphan their branches.
  Documented in README.

## Out of scope (explicitly)

- **Shared / multi-tenant wikis.** The FS mount model assumes the Owner
  is the only writer; there's no per-user separation. Multi-tenant use
  would require a much bigger hardening pass.
- **Public webhook / fork triggers.** Pangolin is owner-triggered only
  — `workflow_dispatch` + optional cron. Running it from
  `pull_request_target` on an untrusted fork is unsafe and unsupported.
- **Shared secrets.** The OAuth token and GH_TOKEN live in GitHub repo
  secrets; pangolin does not rotate them. Rotation is the Owner's job.
- **Model behavior.** We rely on the Anthropic CLI to honor
  `--allowedTools ""`. A buggy or compromised CLI that spawns tools
  anyway is out of scope for this threat model — defense in depth
  (mount-based FS scope, mitmproxy Phase B server-tool block) is what
  catches that class of failure.

## How to extend

- New mode → add an entry to `modes.yml` and run the test suite. The
  invariants in `modes._validate_invariants` fail-closed if the new
  mode violates untrusted-no-tools-no-network-no-gh or misses
  `quarantine_output` when it needs one.
- New tool → add the tool definition to `tools.py` + the name mapping
  to `CLI_TOOL_NAMES`. Only add to a mode's `allowed_tools` after
  considering which trifecta pillar you are creating.
- New writable path → add to the mode's `writable_paths` *and* the
  path-scope tuple in `orchestrate.py` (`_THINKING_ALLOWED_PREFIXES`,
  `_WIKI_INGEST_FORBIDDEN`, etc.). Both layers enforce — changing only
  one is a silent security drift.

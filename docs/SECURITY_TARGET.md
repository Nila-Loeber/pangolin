# Pangolin Security Target (ST)

Style-conformant to ISO/IEC 15408 (Common Criteria) Part 1. **No formal
EAL claim.** This document exists to give a security reviewer a precise
statement of *what pangolin protects, against whom, how, and where the
evidence lives*. For the engineering narrative see
[THREAT_MODEL.md](THREAT_MODEL.md); where the two disagree the code and
the test suite win.

## 1. ST Introduction

### 1.1 ST Reference

| Field | Value |
|---|---|
| ST Title | Pangolin Security Target |
| ST Version | 0.1 (alpha) |
| ST Date | 2026-04-21 |
| Author | Owner (nl) + external reviewer (TÜViT gap analysis, 2026-04-21) |

### 1.2 TOE Reference

| Field | Value |
|---|---|
| TOE Name | Pangolin |
| TOE Version | matches `pangolin.__version__` at `src/pangolin/__init__.py:4–7` |
| TOE Type | Owner-triggered conversational-loop CLI for Git wiki repos |
| Developer | Nila-Loeber (single maintainer) |
| Repository | `github.com/Nila-Loeber/pangolin` |

### 1.3 TOE Overview

Pangolin runs one LLM-driven orchestration cycle per invocation: research
→ ingest → think → write → self-improve → commit → PR. The cycle is
triggered only by the repository Owner (via `workflow_dispatch` or a cron
the Owner controls). There are no inbound webhooks, no public endpoints,
no multi-tenant facets. A cycle may additionally handle one queued
software-mode issue and one PR-feedback iteration.

The security-relevant design principle: **the LLM agent is untrusted**.
Every side effect (filesystem write, GitHub call, egress request) is
mediated by host-side code that re-validates the agent's claims against
the scope it was given.

### 1.4 TOE Description

#### 1.4.1 Physical Scope

The TOE is the Python package `pangolin` (source: `src/pangolin/`) plus
the four OCI images built from the Containerfiles in the repository root:

| Component | Artifact | Role |
|---|---|---|
| Orchestrator | `src/pangolin/` (host-side Python) | Cycle pipeline, scope enforcement, gh/proxy lifecycle |
| `pangolin-agent-llm` | `Containerfile.llm` | Node + claude-CLI, no bash — non-software modes (OAuth) |
| `pangolin-agent-software` | `Containerfile.software` | Node + claude-CLI + bash — software mode only (OAuth) |
| `pangolin-agent-bash` | `Containerfile.bash` | Python + bash, no network — API-key fallback sandbox |
| `pangolin-egress-proxy` | `Containerfile.egress` | mitmproxy + `pangolin_egress.py` addon — sidecar, all agent outbound |

All four images are published to `ghcr.io/nila-loeber/`. The wiki repo
only ships a ~40-line workflow shim; all behaviour-bearing code lives in
the package (SSoT).

#### 1.4.2 Logical Scope

The TOE enforces:

- **Per-mode permission profile** (`modes.yml`): trust-level, allowed
  tools, readable/writable paths, egress tier, container runtime.
- **Container sandboxing** (`orchestrate._base_docker_flags`,
  `_build_mounts`): `--runtime=runsc --read-only --cap-drop=ALL
  --user <uid:gid>`, bind-mount-based filesystem scope.
- **Egress mediation** (`pangolin_egress.py`): hostname allowlist with
  two trust tiers; selective MITM of `api.anthropic.com` only
  (TLS-spliced elsewhere); token injection; server-side-tool body
  inspection.
- **Host-side write validation** (`orchestrate.apply_path_scoped_writes`):
  path-scope allowlists/denylists, traversal rejection, max-write caps,
  containment to REPO root.
- **Cross-check and inference filters** (`execute_triage_decisions`,
  `_research_inference_filter`, `_aggregate_inference_filter`): reject
  agent-claimed actions against issues/files not in the input set or
  not backed by observable artefacts.
- **Owner-activation gates** (`_is_owner_activated`, `_is_owner_comment`):
  require explicit Owner action before any agent-spawned artefact
  becomes live input.

Everything outside these components is explicitly non-TOE and must be
addressed by operational environment objectives (§4.2).

## 2. Conformance Claims

- CC Part 2: **stylistically conformant**, no formal claim.
- CC Part 3: **no formal claim.** No EAL-component evidence (ADV_TDS,
  ALC_CMC, AVA_VAN) is produced.
- Protection Profile conformance: **none** — no applicable PP identified
  for "LLM-orchestrator-on-developer-machine" class.
- Package conformance: **none**.

Purpose of this ST: security-review artefact, not certification basis.

## 3. Security Problem Definition

### 3.1 Assets

| ID | Asset | Protection goal |
|---|---|---|
| AS.TOKEN | `CLAUDE_CODE_OAUTH_TOKEN` (Owner's Claude Max subscription) | Confidentiality |
| AS.GH_TOKEN | `GH_TOKEN` / `GITHUB_TOKEN` (repo scope) | Confidentiality, Integrity (scope) |
| AS.WIKI | Owner's wiki repository content | Integrity, Availability |
| AS.PROVENANCE | `AGENT_MARKER` presence and correctness on agent-authored artefacts | Integrity |
| AS.HOST_FS | Host filesystem outside the wiki repo (`~`, `/etc`, other repos) | Confidentiality, Integrity |

### 3.2 Threat Agents

| ID | Agent | Capability |
|---|---|---|
| TA.INJ | Prompt-injection author | Can place prose in web pages, fragment files, or future collaborator comments |
| TA.HALLU | Hallucinating LLM | The agent itself, unmalicious but unreliable |
| TA.COMP_LLM | Compromised LLM or CLI | Outside scope by A.CLI but shapes DiD posture |
| TA.FUTURE_COLLAB | Future non-Owner GitHub collaborator | Can open issues, post comments — no trigger capability |

### 3.3 Threats

Each threat maps to §3 of THREAT_MODEL.md (adversary model W1–W5).

| ID | Threat | Agent | Asset |
|---|---|---|---|
| T.INJECT | Untrusted input causes the agent to execute attacker-chosen actions (W1) | TA.INJ | AS.WIKI, AS.HOST_FS |
| T.EXFIL_ENV | Agent reads `/proc/self/environ` or similar and sends secrets outbound (W2) | TA.INJ, TA.HALLU | AS.TOKEN, AS.GH_TOKEN |
| T.EXFIL_API | Agent uses the Anthropic API itself (server-side tools) as an exfil channel to attacker-controlled URLs (W2) | TA.INJ | AS.TOKEN payload, AS.WIKI |
| T.SCOPE_FS | Agent reads or writes outside its declared `readable_paths` / `writable_paths` (W3) | TA.INJ, TA.HALLU | AS.HOST_FS, AS.WIKI |
| T.FORGE_ID | Agent produces artefacts indistinguishable from Owner-authored ones (W4) | TA.INJ | AS.PROVENANCE |
| T.LIFECYCLE | Agent closes, reopens, or self-spawns issues it was not asked to process (W5) | TA.INJ, TA.HALLU | AS.WIKI |
| T.SUPPLY | A malicious dependency at `pip install` time ships hostile code into the orchestrator or an agent image | TA.COMP_LLM (broad) | All |

### 3.4 Organisational Security Policies

None. Pangolin is a single-maintainer alpha tool; no OSP applies.

### 3.5 Assumptions

All mirror THREAT_MODEL.md §Assumptions. Each is an environmental
objective at §4.2.

| ID | Assumption |
|---|---|
| A.OWNER | A single human triggers cycles on their own wiki. No other privileged users. |
| A.INFRA | GitHub, Docker + gVisor runtime, Anthropic infrastructure, the host OS, the `claude` CLI, the `gh` CLI, and mitmproxy are honest. |
| A.UNTRUSTED_LLM | The LLM's output is treated as untrusted regardless of provider reliability. |
| A.UNTRUSTED_EXT | Web pages, `wiki/fragment/` contents, and future collaborator comment bodies are attacker-controlled. |
| A.RUNNER | The GitHub Actions runner the Owner dispatches on is not compromised by another tenant. (GitHub-hosted runners or the Owner's self-hosted runner.) |
| A.TOKEN_HYGIENE | The Owner does not commit the OAuth token or GH_TOKEN to version control; rotates on suspicion. |

## 4. Security Objectives

### 4.1 Objectives for the TOE

| ID | Objective |
|---|---|
| O.TRIFECTA | No single agent invocation is given all three of {untrusted input, tool-use, outbound network}. At most two pillars per mode. |
| O.FS_SCOPE | The filesystem view of any agent container contains only paths declared in that mode's `readable_paths` / `writable_paths`. |
| O.TOKEN_ISOLATION | The real Anthropic OAuth token never enters any agent container's process address space or filesystem. |
| O.EGRESS_ALLOWLIST | Agent outbound HTTPS is limited to a hostname allowlist (tight) or to a bounded set of modes (loose). Non-allowed hosts are rejected at the proxy. |
| O.SERVER_TOOL_BLOCK | Anthropic server-side tools (`web_fetch`, `web_search`, `code_execution`, …) are rejected on every `POST /v1/messages` body unless explicitly allowlisted (default empty). |
| O.WRITE_VALIDATION | Direct-schema write claims are applied by host-side code that enforces path prefixes, path denylists, traversal rejection, and per-mode write caps. |
| O.CROSS_CHECK | Agent-claimed issue actions and agent-claimed processed-issue lists are intersected with the input set before any side effect applies. |
| O.INFERENCE_FILTER | Agent-claimed completions are discarded if no on-disk or on-GitHub artefact matches the claim. |
| O.PROVENANCE | Every agent-authored GitHub artefact (issue body, comment, PR body) is prefixed with `AGENT_MARKER`; `_is_owner_*` filters refuse to treat such bodies as Owner input. |
| O.OWNER_ACTIVATION | Agent-spawned mode tickets are inert until explicit Owner activation. |
| O.FAIL_CLOSED | Any unhandled exception in the egress addon terminates the request; the proxy refuses to start without the OAuth token in its environment. |

### 4.2 Objectives for the Operational Environment

| ID | Objective | Satisfies Assumption |
|---|---|---|
| OE.OWNER_SOLE | Repo access is restricted to the Owner; no other committers have admin or workflow-run scope. | A.OWNER |
| OE.RUNTIME | The host provides gVisor (`runsc`), Docker, and outbound iptables/HTTPS_PROXY control. | A.INFRA |
| OE.SECRETS | The Owner stores `CLAUDE_CODE_OAUTH_TOKEN` and `GH_TOKEN` as GitHub repo secrets; does not log, print, or commit them. | A.TOKEN_HYGIENE |
| OE.RUNNER | The Owner uses GitHub-hosted runners (or an equivalently isolated self-hosted runner). | A.RUNNER |
| OE.UPDATES | The Owner updates `PANGOLIN_REF` to a validated SHA before trusting it in production wikis. | A.INFRA |

### 4.3 Rationale (coverage)

Every threat is countered by at least one TOE objective and (where an
assumption applies) one environmental objective.

| Threat | Countered by |
|---|---|
| T.INJECT | O.TRIFECTA, O.OWNER_ACTIVATION, O.PROVENANCE |
| T.EXFIL_ENV | O.TOKEN_ISOLATION, O.EGRESS_ALLOWLIST |
| T.EXFIL_API | O.SERVER_TOOL_BLOCK, O.EGRESS_ALLOWLIST |
| T.SCOPE_FS | O.FS_SCOPE, O.WRITE_VALIDATION |
| T.FORGE_ID | O.PROVENANCE, O.CROSS_CHECK |
| T.LIFECYCLE | O.CROSS_CHECK, O.INFERENCE_FILTER, O.OWNER_ACTIVATION |
| T.SUPPLY | (out of scope — see §7 residual risks; OE.UPDATES partial mitigation) |

## 5. Security Functional Requirements (SFRs)

SFRs are expressed informally. Where possible, each SFR cites the
enforcing module and the asserting test class from `tests/test_security.py`.

### 5.1 Tool-use control (FDP_ACC-style)

- **SFR.TOOL.1 — Per-mode tool allowlist.**
  `modes.yml` defines `allowed_tools` per mode. The CLI path passes
  `--allowedTools "<space-sep list>"` to the claude CLI; the SDK path
  restricts via `ToolExecutor.enabled_tools`. Direct modes have
  `allowed_tools: []` — no tool-use is possible.
  *Enforcing code:* `modes.py`, `orchestrate.spawn_agent_container_*`,
  `tools.ToolExecutor`.
  *Evidence:* `TestSfrTool`.

- **SFR.TOOL.2a — Anthropic endpoint allowlist (default-deny).**
  Only `(POST, /v1/messages)` is permitted on `api.anthropic.com`.
  Every other method/path combination is rejected with a 403 *before*
  the Authorization rewrite, so denied requests never bear the real
  OAuth token upstream. Prevents exfil via `/v1/messages/batches`,
  `/v1/messages/count_tokens`, or any future Anthropic endpoint
  pangolin has not audited. Expanding the allowlist is a
  security-relevant change.
  *Enforcing code:* `pangolin_egress.ANTHROPIC_ENDPOINT_ALLOWLIST`,
  `_endpoint_allowed`, `PangolinEgress.request`.
  *Evidence:* `TestMitmPhaseB::test_anthropic_endpoint_allowlist_default_deny`,
  `TestMitmPhaseB::test_endpoint_deny_precedes_token_injection`.

- **SFR.TOOL.2b — No server-side tools on allowlisted endpoint.**
  For every `POST /v1/messages` body reaching the proxy, any
  tool entry with a `type` field is rejected (403) unless listed in
  `SERVER_TOOL_ALLOWLIST` (default empty).
  *Enforcing code:* `pangolin_egress.PangolinEgress.request`,
  `_validate_messages_body`.
  *Evidence:* `TestMitmPhaseB::test_addon_validates_messages_body`,
  `TestMitmPhaseB::test_server_tool_allowlist_empty_by_default`.

### 5.2 Filesystem scope (FDP_IFC-style)

- **SFR.FS.1 — Mount-based read scope.**
  Paths outside `readable_paths` are not mounted into the agent
  container; they do not exist in its filesystem view.
  *Enforcing code:* `orchestrate._build_mounts`.
  *Evidence:* `TestSfrFs`.

- **SFR.FS.2 — Mount-based write scope.**
  Writable paths are mounted `:rw`; read-only paths are mounted `:ro`.
  *Enforcing code:* `orchestrate._build_mounts`.
  *Evidence:* `TestSfrFs`.

- **SFR.FS.3 — Application-layer scope re-check.**
  The in-process `ToolExecutor` (API-key fallback path) resolves each
  path and rejects traversal (`..`, absolute paths, symlink escapes).
  *Enforcing code:* `tools.ToolConfig.check_readable`,
  `tools.ToolConfig.check_writable`.
  *Evidence:* `TestSfrFs`.

- **SFR.FS.4 — Direct-schema write validation.**
  For every json-schema mode, the host applies writes with:
  - allowed path prefixes per mode,
  - forbidden path subtree list per mode,
  - maximum write count per mode,
  - rejection of traversal and paths outside REPO root.
  *Enforcing code:* `orchestrate.apply_path_scoped_writes`,
  per-mode prefix tuples (`_THINKING_ALLOWED_PREFIXES`, …).
  *Evidence:* `TestQ1DirectWrites`, `TestSfrStruct4`.

### 5.3 Trifecta decomposition (FMT_MSA-style)

- **SFR.TRIFECTA.1 — At most two pillars per mode.**
  For every mode in `modes.yml`, the set
  {untrusted input, tool-use, outbound} has cardinality ≤ 2.
  The research phase split (Phase 1 vs Phase 2) enforces this in
  particular for the research pipeline.
  *Enforcing code:* `modes._validate_invariants`,
  `orchestrate._phase_research`.
  *Evidence:* `TestSfrTrifecta`, `TestEpic9PhaseSplit`.

### 5.4 Egress mediation (FTP_ITC-style)

- **SFR.EGRESS.1 — Hostname allowlist (tight).**
  Tight-tier requests to hosts outside `TIGHT_ALLOWLIST` receive a 403
  from the proxy.
  *Enforcing code:* `pangolin_egress.PangolinEgress.tls_clienthello`,
  `PangolinEgress.request`.
  *Evidence:* `TestMitmPhaseA`.

- **SFR.EGRESS.2 — Selective MITM.**
  Only SNI `api.anthropic.com` is bumped; all other SNIs in the
  allowlist are TLS-spliced (raw tunnel, no MITM).
  *Enforcing code:* `pangolin_egress.PangolinEgress.tls_clienthello`.
  *Evidence:* `TestMitmPhaseA`.

- **SFR.EGRESS.3 — Token injection (Phase A).**
  The addon strips incoming `Authorization` headers and injects
  `Bearer <real-token>` for `api.anthropic.com` only. The real token
  is read from the proxy's environment variable `ANTHROPIC_TOKEN`.
  *Enforcing code:* `pangolin_egress.PangolinEgress.request`.
  *Evidence:* `TestMitmPhaseA`.

- **SFR.EGRESS.4 — Fail-closed proxy posture.**
  The proxy refuses to start without `ANTHROPIC_TOKEN` set.
  mitmproxy default-kills requests on unhandled addon exceptions.
  *Enforcing code:* `orchestrate._ensure_proxy_running`,
  mitmproxy runtime default.
  *Evidence:* `TestMitmPhaseA` (startup), `TestHardening`.

### 5.5 Provenance and Owner activation (FIA_UAU-style, non-crypto)

- **SFR.PROV.1 — Agent marker on all agent-authored bodies.**
  Issue bodies, comment bodies, and PR bodies produced by a cycle are
  prefixed with `AGENT_MARKER = "<!-- pangolin:auto -->"`.
  *Enforcing code:* `orchestrate` (issue/comment/PR creation sites).
  *Evidence:* `TestAgentCommitEmailShared`, `TestPendingComments`.

- **SFR.PROV.2 — Owner-comment filter.**
  `_is_owner_comment` treats any comment carrying `AGENT_MARKER` or
  authored by a bot-style login as non-Owner, regardless of GitHub
  author identity.
  *Enforcing code:* `pr_feedback._is_owner_comment`.
  *Evidence:* `TestIsOwnerComment` (in `test_pr_feedback.py`).

- **SFR.PROV.3 — Owner activation of agent-spawned tickets.**
  Agent-spawned mode tickets (e.g. self-prompted "mode:software") are
  treated as inert until the Owner explicitly comments on them.
  *Enforcing code:* `orchestrate._is_owner_activated`.
  *Evidence:* `TestEpic10OwnerTrigger`.

### 5.6 Cross-check and inference filters (FDP_ACF-style)

- **SFR.STRUCT.1 — Triage decision cross-check.**
  `execute_triage_decisions` rejects `comment`/`label`/`close` actions
  whose target issue was not in the input set.
  *Enforcing code:* `orchestrate.execute_triage_decisions`.
  *Evidence:* `TestSfrStruct`, `TestSfrStruct4`.

- **SFR.STRUCT.2 — Summary comment cross-check.**
  Same contract as STRUCT.1 for `execute_summary_comments`.
  *Enforcing code:* `orchestrate.execute_summary_comments`.
  *Evidence:* `TestSfrStruct`.

- **SFR.STRUCT.3 — report_processed tool cross-check.**
  In the SDK fallback path, the `report_processed` tool rejects
  non-eligible issue numbers *inside the tool*, not in a post-hoc
  parser. The agent sees the rejection; `executor.processed` contains
  only cross-checked numbers.
  *Enforcing code:* `tools.ToolExecutor._report_processed`.
  *Evidence:* `TestSfrStruct4`.

- **SFR.STRUCT.4 — Inference filter: observable-evidence requirement.**
  - Research: only claims backed by a fragment file with
    `source_issue: <n>` in frontmatter survive.
  - Thinking / writing / self-improve: if the agent wrote nothing in
    its writable scope, *every* processed-issue claim is dropped.
  - PR-feedback: progress reply + push only if a real diff landed.
  *Enforcing code:* `orchestrate._research_inference_filter`,
  `_aggregate_inference_filter`, `pr_feedback` diff guard.
  *Evidence:* `TestSfrStruct4Inference`, `TestPendingComments`.

### 5.7 Quarantine (FDP_ITT-style)

- **SFR.QUAR.1 — Fragment frontmatter host-generated.**
  `wiki/fragment/*.md` frontmatter (`source_issue`, `captured_at`,
  `captured_by`) is written by the host-side
  `_write_research_fragment`, not by the agent.
  *Enforcing code:* `orchestrate._write_research_fragment`.
  *Evidence:* `TestResearchDocSplit`.

- **SFR.QUAR.2 — Validator deletes unframed fragments.**
  `validate_output.sh research` (in `default_config/`) deletes any
  fragment missing required frontmatter before the cycle commits.
  *Enforcing code:* `default_config/validate_output.sh`.
  *Evidence:* `TestHardening`.

- **SFR.QUAR.3 — Wiki-ingest cannot rewrite its own source.**
  Wiki-ingest's writable-path set allows `wiki/` but forbids
  `wiki/fragment/`, `wiki/SCHEMA.md`, `wiki/index.md`.
  *Enforcing code:* `orchestrate._WIKI_INGEST_FORBIDDEN` (or
  equivalent constant), `modes.yml`.
  *Evidence:* `TestQ1DirectWrites`.

### 5.8 Modes invariants (FMT-style)

- **SFR.MODES.1 — Invariant validation.**
  `modes._validate_invariants` fails-closed if:
  - `trust_level: untrusted` AND (`code_execution: true` OR missing
    `quarantine_output`),
  - `readable_paths` or `writable_paths` empty,
  - `writable_paths ⊄ readable_paths`.
  *Enforcing code:* `modes._validate_invariants`.
  *Evidence:* `TestModesConsistency`.

## 6. TOE Summary Specification (TSS)

Mapping of each security-functional area to the enforcing components.

| Area | Host-side | Proxy-side | Container-side |
|---|---|---|---|
| Tool control | `tools.ToolExecutor`, `orchestrate.spawn_agent_container_tooluse` `--allowedTools` | `_endpoint_allowed` (endpoint allowlist), `_validate_messages_body` (Phase B body check) | CLI's own allowed-tools flag honoring |
| FS scope | `_build_mounts`, `ToolConfig.check_*` | — | `--read-only`, bind-mounts |
| Trifecta | `modes.yml` + `_validate_invariants`, `_phase_research` split | — | Image choice (llm vs software vs bash) |
| Egress allowlist | `_ensure_proxy_running`, `_proxy_url`, `HTTPS_PROXY` in `_base_docker_flags` | `tls_clienthello`, `request` host check | `NODE_EXTRA_CA_CERTS`, no direct egress |
| Token isolation | `CLAUDE_CODE_OAUTH_TOKEN` → proxy env `ANTHROPIC_TOKEN`; placeholder injected into agent env | `request` Authorization strip + inject | No OAuth token in `/proc/self/environ` |
| Write validation | `apply_path_scoped_writes`, `execute_*` | — | — |
| Cross-check | `execute_triage_decisions`, `execute_summary_comments`, `ToolExecutor._report_processed` | — | — |
| Inference filter | `_research_inference_filter`, `_aggregate_inference_filter`, pr-feedback diff guard | — | — |
| Provenance | `AGENT_MARKER` prepend at creation sites, `_is_owner_comment`, `_is_owner_activated` | — | — |
| Quarantine | `_write_research_fragment`, `validate_output.sh`, `modes.yml` path rules | — | — |
| Fail-closed | `_ensure_proxy_running` token check | mitmproxy default exception handling | — |

Runtime topology: at cycle start, `_ensure_proxy_running` brings up the
proxy on `pangolin-net`. All agent containers receive
`HTTPS_PROXY=http://<proxy-ip>:<tight|loose>` via `_base_docker_flags`.
The proxy generates a runtime CA per startup and publishes the public
cert to volume `pangolin-proxy-ca`, which every agent mounts read-only
at `/etc/pangolin/proxy-ca.crt`.

## 7. Residual Risks

These are known limitations of the current TOE and should be read
together with BACKLOG.md.

| ID | Residual | Mitigation posture |
|---|---|---|
| R.SUPPLY_APK | Alpine apk pins are mutable; `ca-certificates` already rotated once. | Image reproducibility on BACKLOG (renovate + digest-pinning). |
| R.SUPPLY_SBOM | No published SBOM, no SCA run in CI. | On BACKLOG (CycloneDX + image scanner). |
| R.HOST_EGRESS_BYPASS | iptables REJECT was removed 2026-04-21 (broke GH-Actions log uploads); only `HTTPS_PROXY` export remains. A raw-socket library that ignores proxy env would bypass. | Accepted for single-user alpha. Assumption A.INFRA (honest pip/gh/httpx) covers this in-scope. |
| R.CLI_TRUST | The claude CLI's adherence to `--allowedTools ""` is an assumption (A.INFRA). | Defense-in-depth: mount-based FS scope (tools that reach outside the mount can't see targets), egress hostname allowlist (WebFetch to attacker host blocked), Anthropic endpoint allowlist (CLI can't smuggle via non-`/v1/messages` paths), and Phase B server-tool block (typed tools rejected on the one allowed endpoint). |
| R.TIMEOUT | Software-mode 180 s timeout truncates long tool-use loops. | Not a security risk — kills wedged agents. PR-feedback loop is the continuation mechanism. |
| R.PR_INLINE | Inline review-thread comments not yet consumed by the PR-feedback loop. | Phase 2 on BACKLOG; no security risk, only missed conversational signal. |
| R.MULTI_TENANT | FS mount model assumes single-writer Owner. | Out of scope (assumption A.OWNER). Shared wikis would require a new ST. |
| R.ROTATION | OAuth and GH tokens are not rotated by pangolin. | Environmental objective OE.SECRETS (Owner rotates on suspicion). |

## 8. Change log

| Date | Author | Change |
|---|---|---|
| 2026-04-21 | Owner + TÜViT gap review | Initial ST, structured lift from THREAT_MODEL.md |

## 9. Relationship to THREAT_MODEL.md

THREAT_MODEL.md is the engineering-facing threat narrative (assumptions
→ adversaries → defenses-in-code → known gaps). This ST is the
review-facing structural companion (assets → threats → objectives →
SFRs → TSS → residuals). They should not disagree; if they do, file an
issue and update both. For day-to-day code work, THREAT_MODEL.md is
easier to scan; for a security review, this ST is the entry point.

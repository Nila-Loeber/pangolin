# Changelog

Pangolin uses git tags as the version source of truth (`setuptools_scm`).
This file documents the user-visible changes per tagged release.

## v0.12.2 — 2026-04-30

### Fixed

- **Search-phase tool-use gate was throwing away real work.** The
  research-search defense added in v0.12.0 read
  `usage.server_tool_use.{web_search_requests, web_fetch_requests}`
  to verify the agent had reached out to the web. Empirical
  reproduction (issue #432, run 25153091070, plus a direct repro:
  `claude --print --allowedTools WebSearch,WebFetch ...`) showed
  the CLI now dispatches `WebSearch`/`WebFetch` to a helper
  `claude-haiku-4-5` model and surfaces those counts under
  `modelUsage[<model_id>].webSearchRequests`, leaving the
  top-level field at zero even on successful searches with real
  URLs and full-cost runs ($1.05, 18 turns, 4.3 minutes).

  Rather than chase the per-model counter location (which already
  shifted once and might shift again), `spawn_agent_container_direct`
  now uses `--output-format stream-json --verbose` and counts
  `tool_use` blocks named `WebSearch`/`WebFetch` directly from the
  CLI's emitted stream. This is the canonical Agent-SDK shape
  (every tool call appears as a structural `tool_use` content
  block in an `assistant`-typed event), independent of which
  model the CLI dispatches the call to and which envelope fields
  it uses for per-model bookkeeping. `_envelope_summary` now also
  includes a per-tool-name breakdown so future verbose runs make
  the actual dispatch visible directly.

### Changed

- `spawn_agent_container_direct` switches CLI output format from
  `json` to `stream-json --verbose`. Return contract is unchanged
  (still `dict | str` from the final result event). Callers that
  read `envelope.result` (every direct mode: writing, thinking,
  summarise, wiki-ingest, search) see the same content. Stderr
  becomes a bit noisier under `PANGOLIN_VERBOSE=1` because the
  CLI's own verbose logs flow through.

### Removed

- Internal helper `_server_tool_use_count` (replaced by
  `_count_tool_uses` over the stream-json events). Not part of
  the public API.

## v0.12.1 — 2026-04-30

### Added

- **Verbose envelope dump.** `PANGOLIN_VERBOSE=1` now emits a compact
  CLI-envelope summary (`is_error`, `stop_reason`, `num_turns`,
  `duration_*`, `total_cost_usd`, `permission_denials`, full `usage`
  including `server_tool_use`, 500-char `result_preview`) right after
  parse in `spawn_agent_container_direct`. Drop-decisions downstream
  (is_error, tool-use gate, etc.) now have the envelope context in
  the same log block. Bulky `result` field excluded. Also dumps raw
  stdout on JSON-parse failure under verbose.
- **Post-cycle proxy log dump.** Verbose runs now `docker logs --tail
  1000` the egress proxy at the end of `run_cycle`, so mitm
  BLOCK/PASS/endpoint-deny verdicts survive past workflow
  termination. Bridges the gap between "tool-use gate fired" and
  "why the proxy decided what it did".
- **Paired-test policy coherence.** New `TestSecurityPolicyCoherence`
  class catches the structural drift class behind PR #433 (one
  policy individually correct, another individually correct, the
  composition broken). Six AST-static tests assert: every
  `spawn_agent_container_direct` call invoking WebSearch/WebFetch
  uses loose egress + `min_server_tool_calls>=1`; every server-tool
  prefix we invoke is allowlisted in the proxy; CLAUDE.md and the
  search-agent SSoT prompt do not claim WebSearch/WebFetch are
  client-side. Drift sabotage round-trip verified.

### Fixed

- **Search-agent SSoT prompt.** `docs/research-search-agent.md`
  described WebSearch/WebFetch as "client-side CLI tools, not the
  API's server-side tool infrastructure" — wrong post-PR #31 (and
  the same mistaken claim that seeded the original incident).
  Replaced with an accurate description plus an explicit "must call
  ≥1 web tool per request" instruction, so the model can't
  hand-wave past the orchestrator's tool-use gate.
- **CLAUDE.md leftover claim.** A second instance of the wrong
  client-side claim survived the PR #31 fix; corrected.

## v0.12.0 — 2026-04-30

### Fixed

- **Research confabulation (PR #433 incident).** The Claude CLI's
  `WebSearch` and `WebFetch` are Anthropic server-side tools
  (`web_search_*` / `web_fetch_*` entries in the Messages API
  request body), not client-side as previously assumed. Pangolin's
  egress proxy was blanket-blocking every tools[] entry with a `type`
  field, so research-search phase 1 had been silently failing — the
  agent fell back to training-data prose, dressed it up with
  plausible URLs and document titles, and the schema validator
  passed it through. Three layers of defense added; any one would
  have caught the incident.
  - **Egress policy.** New `LOOSE_PORT_TOOL_TYPE_PREFIXES =
    ("web_search_", "web_fetch_")` in `pangolin_egress.py`. Loose
    port (3129, research-search only) now permits these two
    server-tool families via prefix-match; tight port (every other
    mode, including summarise) keeps the block in force.
    `code_execution_*` and any future server-tool family stay
    default-denied on both ports. Trade-off accepted: server-side
    `web_fetch` is opaque to the proxy, but research has no Read
    tool, the OAuth token is off the container (Phase A), and the
    only readable content is owner-authored issue text.
  - **Tool-use gate.** New `min_server_tool_calls` parameter on
    `spawn_agent_container_direct`. Phase-1 search passes 1; the CLI
    envelope's `usage.server_tool_use.{web_search_requests,
    web_fetch_requests}` must be ≥1 or the result is dropped and the
    issue stays open for retry. Independent of how the agent phrased
    its output.
  - **Confabulation hard-stop.** `_write_research_fragment` rejects
    findings whose `source` or `summary` contain markers like
    `training-data`, `unverified`, `proxy block`, `could not verify`
    (case-insensitive, German variants included). Last-line defense
    against an agent that admits the content is fabricated.
- **CLI `is_error` handling.** When the Claude CLI reported
  `is_error: true`, the `result` field carrying the error string
  ("Invalid bearer token", etc.) flowed through to downstream phases
  as if it were upstream content. `spawn_agent_container_direct` now
  drops the result on `is_error`.

### Changed

- `CLAUDE.md` egress section corrected: the claim that the CLI uses
  client-side WebSearch/WebFetch was wrong; both are server-side and
  go through the proxy's body inspection.

## v0.11.0 — 2026-04-28

### Fixed

- **Cycle PR drift.** `_phase_wiki_index` regenerated `wiki/index.md`
  via an LLM each cycle. The output was non-deterministic (link-prefix
  flips like `../drafts/` ↔ `drafts/` ↔ `draft/`, adjacent-entry swaps),
  so every cycle produced a diff and a PR even on no-op runs. Replaced
  with a pure-Python renderer that preserves existing
  titles/descriptions for known paths and extracts H1 + first
  non-heading line for new files. Output is stable across runs.
- **No-op cycle gating.** `_phase_wiki_ingest` used to append a line to
  `wiki/log.md` on every run (e.g. "0 absorbed, 0 new topics, 2
  skipped"), enough to force a PR. The log line now writes only when a
  page was written or the watermark advanced. Combined with the
  deterministic index, true no-op cycles produce zero diff → no PR.
- **Cycle-summary hallucination.** `_phase_summary` fed the LLM a huge
  INBOX payload (full ticket bodies + comments) plus a `CHANGED` list
  of just file names. With no concrete diff evidence, the agent
  paraphrased inbox topics as if the cycle had produced them. Fixed in
  three layers: (a) skip the phase entirely when no PR was created;
  (b) skip when CHANGED contains only `wiki/index.md`/`wiki/log.md`/
  `.ingest-watermark`; (c) pass `git diff --stat` (line counts per
  file) alongside file names so the agent has numeric ground truth;
  (d) tightened `docs/inbox-summary.md` SSoT with an explicit
  anti-hallucination rule.

### Added

- **Wiki-page links in inbox-summary comments.** New
  `pages_per_ticket: [{issue, pages}]` field in the wiki-ingest
  schema. The ingest agent reports which inbox tickets contributed to
  which resulting wiki pages (fragment filenames already carry the
  `issueNNN` source). The orchestrator stores the mapping; the summary
  phase appends a host-rendered `**Wiki:**` footer with absolute
  GitHub URLs, so Nila can jump from a ticket to the resulting page on
  mobile. Link rendering is host-side, not LLM-side, so paths can't be
  dropped, invented, or mangled.

## v0.1.0 — 2026-03

Initial tagged release.

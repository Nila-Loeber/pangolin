# Changelog

Pangolin uses git tags as the version source of truth (`setuptools_scm`).
This file documents the user-visible changes per tagged release.

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

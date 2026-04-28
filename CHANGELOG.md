# Changelog

Pangolin uses git tags as the version source of truth (`setuptools_scm`).
This file documents the user-visible changes per tagged release.

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

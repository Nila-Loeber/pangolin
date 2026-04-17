# Wiki Schema

The wiki is the repo's consolidated knowledge store. All original thinking,
researched sources as synthesis, project status, references. External raw
sources do **not** live here (they stay in `wiki/fragment/` or outside the
repo).

Inspired by Karpathy's [LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) (April 2026): instead of querying raw documents at runtime via RAG, an LLM agent incrementally compiles new captures into a structured, prose-synthesised wiki that compounds over time. The fragment → topic absorption flow below is the structural realisation.

## Design principles

1. **Wiki = the central repo for all original knowledge.** External source
   documents in raw form stay outside or in `wiki/fragment/`. Everything
   else — syntheses, ideas, positions, project state — lives here.
2. **Flat hierarchy, deep cross-linking.** Subdirectories are *page types*,
   not taxonomies. A page belongs in *one* directory but may have any
   number of cross-references. Linking beats categorisation.
3. **Pages are atoms.** One page = one concept, one person, one project.
   Two short pages beat one long one that covers two topics. Granularity
   enables cross-linking.
4. **Growth through splitting, not through bloat.** When a page gets long
   (rule of thumb: >300 lines) it is split. The parent becomes a hub page
   with links to the children.
5. **Convention over configuration.** File names = URL slugs. Directory
   structure = page type. **No YAML frontmatter** on topic/ref/project/
   draft pages. The structure *is* the metadata.
6. **The index is generated, not curated.** `wiki/index.md` is regenerated
   by the wiki-ingest agent from the filesystem. No manual table of
   contents.
7. **Convivial tools (Illich).** The wiki is meant to support thinking, not
   replace it. No completeness pressure — gaps are fine; explicitly flagged
   gaps are better than fake coverage.

## Three layers

1. **Raw sources & fragments**: `wiki/fragment/`. Raw single captures —
   produced by the research agent (with YAML frontmatter for the audit
   trail) or dropped in by the Owner manually. **Mixed-trust** — see
   THREAT_MODEL.md.
2. **Wiki (synthesised)**: everything else under `wiki/`. Edited by the
   wiki-ingest agent (thinking profile, trusted) or by the Owner.
3. **Schema (config)**: this file + `docs/wiki-ingest.md` as the SSoT for
   the ingest agent.

## Directory layout

```
wiki/
├── SCHEMA.md              # This file (read-only for the ingest agent)
├── index.md               # Auto-generated overall index
├── log.md                 # Chronological ingest protocol
│
├── *.md                   # Topics/concepts (top level)
│
├── ref/                   # People & reference thinkers
│   └── *.md
│
├── project/               # Projects
│   └── *.md
│
├── draft/                 # Blog-post drafts & raw pieces
│   └── *.md
│
└── fragment/              # Raw captures (research output + manual)
    └── YYYY-MM-DD-<slug>.md
```

### When do we add a new subdirectory?

Only when:
- A clearly delimited **page type** emerges (not: a topic cluster)
- At least 5 pages of that type are in sight
- The type is differentiated by **structure**, not only by topic

Topic clusters (e.g. "everything on security") are solved via hub pages,
**not** via subdirectories. Directories = types, not categories.

## Page types

| Type | Directory | Frontmatter? | Content |
|---|---|---|---|
| **Topic/concept** | `wiki/` | no | Synthesis. Core arguments, cross-links, open questions. |
| **Person/reference** | `wiki/ref/` | no | Short profile, relevant works, where referenced in the project. |
| **Project** | `wiki/project/` | no | Status, goals, relevant wiki pages, next steps. |
| **Draft** | `wiki/draft/` | no | Raw pieces. Either become posts or get absorbed back into a topic. |
| **Fragment** | `wiki/fragment/` | **yes** (audit trail) | Unprocessed raw captures. Schema below. |
| **Index** | `wiki/` | no | Auto-generated overview of all pages. |
| **Log** | `wiki/` | no | Chronological protocol of the ingest runs. |

### Fragment schema (the only page type with frontmatter)

```markdown
---
title: <short title of the capture>
source: <URL or clean textual citation>
date: <YYYY-MM-DD publication date of the source>
summary: <2-4 sentences plain text>
source_issue: <issue number that triggered the research request>
captured_at: <YYYY-MM-DDTHH:MM:SSZ timestamp of the capture>
captured_by: <"research-bot" | "manual">
---

## Summary

<prose summary>

## Why relevant

<why this matched the request>
```

Fragments are **archival** — the wiki-ingest agent may read them but **must
not modify or delete them**. The audit trail "wiki page X contains a
sentence from fragment Y" must remain intact. Enforcement: see `scripts/validate-output.sh wiki-ingest`.

### Filename-slug convention

- Fragment: `YYYY-MM-DD-issue<N>-<short-slug>.md` (e.g. `2026-04-12-issue47-dopamine-knowledge.md`)
- Topic/ref/project/draft: `<slug>.md` without a date (e.g. `lethal-trifecta.md`)

Slug = lowercase, hyphens instead of spaces, only `[a-z0-9-]`, max 50
characters.

## Scaling mechanisms

### Hub pages

When a topic cluster emerges (>5 pages with strong mutual references), a
**hub page** is created. It contains:

- 3-5 sentences of overview
- Ordered links to the cluster pages with a short description
- Open questions / gaps in the cluster

The wiki-ingest agent may propose hub pages but must not unilaterally
re-purpose an existing short page into a hub.

### Fragment processing

Fragments flow through a lifecycle:

```
captured (wiki/fragment/ — fresh, not yet ingested)
  ↓ (wiki-ingest agent during a cycle run)
absorbed (integrated into one or more wiki/<topic>.md; the fragment file stays archival)
```

The watermark `.ingest-watermark` (repo root) tracks which fragments the
ingest agent has already seen.

## What does NOT belong in the wiki

- Code (goes in `scripts/`, `tools/`, etc.)
- Raw research output before synthesis (wiki fragments are OK, but only
  after human review via PR merge)
- Client data (stays in issues, not in repo files)
- Secrets, credentials, tokens (never in the repo at all)
- Current task lists (belong in GitHub issues)

## What is NOT in this SCHEMA file

Personal preferences around writing style, language, topics. Those live in
project-specific companion documents (e.g. `docs/voice.md` if present).
This file is only the structural convention.

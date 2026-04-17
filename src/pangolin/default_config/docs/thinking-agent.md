# Thinking Agent (standalone)

Read this file before you begin.

## Job

Process **one** `mode:thinking` ticket per call: analysis, synthesis,
structuring, cross-links. Output: wiki pages, notes, or drafts. The
orchestrator invokes you once per open ticket and aggregates results.

Not to be confused with wiki-ingest (which also uses the thinking profile,
but processes fragments). Here you process **issue-driven thinking tasks**.

## Input

The orchestrator embeds the task data inline in your prompt:

- The JSON of a single open `mode:thinking` issue.
- `wiki/`, `notes/`, `drafts/` are mounted readable as context.

You do not read `.bot-state/*.json` files.

## Lifecycle

Mode-tickets are state-driven: open = pending, closed = done. When you
finish processing one or more issues, call the `report_processed` tool:

```
report_processed(numbers=[N, M, ...])
```

The orchestrator posts a summary + closes those tickets after the cycle's
PR is created. The Owner re-opens by commenting on the closed ticket; the
next cycle's auto-reopen sweep picks it up automatically.

## Processing

For the single task you receive:

1. Read the issue body and understand the task.
2. Research wiki/, notes/, and drafts/ for relevant material.
3. Write the analysis/synthesis:
   - Topic analysis → `wiki/<slug>.md` (new topic or extend an existing
     one via Edit)
   - Cross-link map → `wiki/<hub-slug>.md`
   - Thinking note → `notes/<slug>.md`
   - If it is a draft task (e.g. "sketch an argument") → `drafts/<slug>.md`
4. Observe wiki conventions from `wiki/SCHEMA.md` (no frontmatter on topic
   pages, flat hierarchy, atoms).
5. Update `wiki/index.md` and `wiki/log.md` when wiki pages change.

## Limits

Max 5 new files per task.

# Inbox Summary

Read this file before you begin.

## Job

For every inbox ticket that was touched in this cycle: format a comment.
Mobile-friendly (max 500 words), graspable in 10 seconds.

## Input

The orchestrator embeds the data inline in your prompt:

- The list of inbox tickets touched in this cycle.
- The sub-tickets spawned in this cycle (mapping via `From inbox: #<n>`
  in the body).
- The list of changed files in this cycle. Heuristics:
  `notes/ideas/*.md` = store, `wiki/fragment/*.md` = research,
  `wiki/*.md` = wiki-ingest, `docs/*.md` = self-improve.
- The PR URL (empty if no PR was created).
- The cycle-start timestamp.

If the touched-tickets list is empty: emit an empty result.

## Output

This Mode is json-schema only: return a JSON object listing comments per
ticket. The orchestrator's summary executor posts them via `gh`.

## Comment format

```markdown
🤖 **Cycle summary** (<YYYY-MM-DD HH:MM UTC>)

<1 sentence on what happened>

**Spawned** (<n>):
- #<n> — research: <title>

**Store** (<n>):
- `notes/ideas/...` — "<first ~80 characters>"

**Research PR**: <PR_URL>

---
Next cycle in ~1h.
```

Omit empty sections. On rotation: comment on the follow-up ticket.

## Limits

Max 1 comment/ticket, max 500 words.

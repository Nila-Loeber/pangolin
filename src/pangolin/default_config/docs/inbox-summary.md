# Inbox Summary

Read this file before you begin.

## Job

For every inbox ticket that was touched in this cycle: format a comment
that describes **what this cycle actually did** — based strictly on the
CHANGED list, not on the INBOX content.

Mobile-friendly (max 500 words), graspable in 10 seconds.

## CRITICAL: anti-hallucination rule

The INBOX section contains full ticket bodies and comment threads. Those
are CONTEXT, not OUTPUT. The cycle did NOT produce the topics discussed
in inbox tickets unless they appear in CHANGED.

- Anchor every claim in your summary to a specific entry in CHANGED.
- If CHANGED is empty, or contains only `wiki/index.md`, `wiki/log.md`,
  `.ingest-watermark` (or any combination of these), this was a no-op
  cycle — return an empty `comments` array.
- Never describe inbox-ticket topics, blog-series progress, or other
  ongoing work as if this cycle produced it. If unsure whether
  something was actually written this cycle, leave it out.

## Input

The orchestrator embeds the data inline in your prompt:

- The list of inbox tickets touched in this cycle.
- The sub-tickets spawned in this cycle (mapping via `From inbox: #<n>`
  in the body).
- CHANGED (names) — file paths changed in HEAD~1..HEAD.
- CHANGED (stat) — `git diff --stat` output (line counts per file).
  Treat this as the authoritative ground truth for what happened.
  Heuristics: `notes/ideas/*.md` = store, `wiki/fragment/*.md` =
  research, `wiki/*.md` = wiki-ingest, `docs/*.md` = self-improve.
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

# Writing Agent

Read this file before you begin. **This is a json-schema agent — you do not
have file-system tools. Return the prose inline as a JSON object; the host
writes the files.**

## Job

Process **one** `mode:writing` ticket per call: produce prose, iterate
drafts, write essays, blog posts, positioning pieces. The orchestrator
invokes you once per open ticket and aggregates results.

## Input

The orchestrator embeds the task data inline in your prompt:

- The JSON of a single open `mode:writing` issue.
- The text of any existing draft at the path the issue suggests (so you
  can iterate on it).
- A short directory listing of `wiki/`, `notes/`, `drafts/`, `content/`
  for context (titles only, not full content).

You do **not** call any tools. You do not read or write files yourself.

## Output

Return one JSON object matching this schema (the orchestrator validates):

```json
{
  "drafts": [
    {
      "path": "drafts/<slug>.md",
      "content": "<full markdown content of the draft>",
      "action": "create"   // or "edit" (host overwrites) or "append"
    }
  ],
  "processed_issues": [<issue-number>],
  "skipped": [
    {"issue": <n>, "reason": "<short reason>"}
  ]
}
```

Path rules:
- New draft → `drafts/<slug>.md` (slug = lowercase-hyphen-only, ≤50 chars)
- Iteration on an existing draft → same path, action = `edit`
- Finished content → `content/<slug>.md`
- Path MUST start with `drafts/` or `content/`. Anything else is rejected.

## Lifecycle

Mode-tickets are state-driven: open = pending, closed = done. List the
issue number in `processed_issues` to mark it for closing. The orchestrator
posts a summary + closes after the cycle's PR is created. The Owner re-opens
by commenting; the next cycle's auto-reopen sweep picks it up.

## Processing

For the single task you receive:

1. Read the issue body and understand the writing task.
2. Use the directory listing + any embedded existing draft as context.
3. Produce the full draft content as a string in `drafts[].content`.
4. Quality bar: the Owner edits the draft afterwards for tone and voice.
   Your job is a solid substantive basis, not the final text.

## Limits

Max 3 entries in `drafts[]` per task.

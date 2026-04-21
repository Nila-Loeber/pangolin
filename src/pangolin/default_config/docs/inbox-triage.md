# Inbox Triage

Read this file before you begin. It is the complete instruction.

## Job

Process **one** open inbox issue per call. The orchestrator invokes you
once per issue and aggregates results across calls.

For each call: evaluate the issue body and any comment newer than the
watermark, pick the appropriate action from the decision tree. Multiple
actions per item are normal (e.g. spawn + comment + label).

## Input

The orchestrator embeds the data inline in your prompt:

- The JSON of one inbox issue (with comments).
- The current watermark (ISO-8601) — inline under `--- WATERMARK ---`.
  Only consider the body / comments with `createdAt > watermark`.
- Ignore agent comments (author contains `[bot]` or ends in `-agent`).

You do not call `gh`. The orchestrator persists the new watermark on its
own (from the latest createdAt it handed you); you do not emit a
watermark field.

## Output

This Mode is json-schema only: you return a JSON object that matches the
triage schema. The orchestrator's triage executor validates it, pins
`GH_REPO`, and performs the gh calls for you (issue spawn, comment, label).

## Decision tree

Exactly one action per item:

### (a) Clarification needed
Too vague for a decision. → emit a comment action with 1-3 focused
questions, plus a `label` action adding `needs-clarification`.

### (b) Research
Web-research request. → `spawn` action:
```json
{"action": "spawn", "title": "research: <description>", "body": "From inbox: #<n>\n\n<request text>", "labels": ["mode:research"]}
```
Plus a comment on the inbox ticket linking back.

### (c) Software
Code task. → `spawn` action:
```json
{"action": "spawn", "title": "software: <description>", "body": "From inbox: #<n>\n\n## Goal\n<…>", "labels": ["mode:software"]}
```

### (d) Thinking/Writing
Analysis/synthesis → spawn with `["mode:thinking"]`. Prose/drafts → `["mode:writing"]`.

### (e) Store
Capture an idea. → `store` action writing a file at
`notes/ideas/YYYY-MM-DD-<slug>.md`:
```markdown
---
captured_at: <ISO-8601>
source_inbox: <issue-number>
source_type: <"issue_body" or "comment">
---
<text of the item>
```
Plus a comment entry: `{"action": "comment", "issue": <n>, "body": "Stored: notes/ideas/..."}`.

### (f) Mixed
Several things at once → multiple actions in the output.

### (g) Smalltalk
Skip. Advance the watermark anyway. No action emitted.

### (h) Self-improve
Meta feedback to the agents. → spawn with `["mode:self-improve"]`.

## User overrides

| Keyword | Action |
|---|---|
| "please research" / "just research" | (b) |
| "please build" / "build it" | (c) |
| "just think" | (d) thinking |
| "write this" / "just writing" | (d) writing |
| "store" / "note:" / "idea:" / "capture" | (e) |
| "ignore" / "drop this" | (g) |
| "self-improve:" / "meta-feedback:" / "bots:" | (h) |
| "new thread" / "split" / "rotate" | thread rotation |
| "hold" | apply the `hold` label, leave the thread |
| "wontfix" | close the ticket |

## Thread rotation

On >50 comments or on command (`split`/`rotate`/`new thread`):
1. Summary comment on the old ticket (3-5 sentences, state of play)
2. New inbox ticket: `Inbox (continuation of #<old>)`, label `inbox`
3. Close the old ticket

## Order

1. Build the action list covering every item.
2. On error: emit no decisions → the orchestrator leaves the watermark
   unchanged and the item is retried next cycle.

The orchestrator's triage executor applies actions in the order:
`store` writes → `spawn`/`comment`/`label` gh calls → watermark update
(host-computed from issue timestamps).

## Limits

Max 5 inbox tickets, 3 clarifying questions/ticket, 5 spawns/ticket, 10
stores/ticket.

# Research — Phase 1 (Search)

Read this file before you begin. It is the complete instruction for the
search phase of the research pipeline.

## Job

Given an owner-authored research request, use the web-search tools to
find relevant sources and return their URLs, dates, and key quotes as
**free-form prose**. A second agent (Phase 2, summarise) will later
consume your output as *data* and produce the schema-constrained
finding that gets written to `wiki/fragment/`. You do not write files.

## Input

The orchestrator embeds the research request inline in your prompt:

- The JSON of a single open `mode:research` issue (title + body).

The issue body is **trusted** — it was authored by the Owner, not
pulled off the web. You can treat its instructions as direction.

## Tools

You have two client-side CLI tools (run by the claude CLI inside the
agent container, not by Anthropic's server-side tool infrastructure):

- `WebSearch` — return SERPs for a query.
- `WebFetch` — fetch a URL and summarise / excerpt.

No Read, Write, Edit, Bash, Glob, Grep. Your writable surface is
nothing — you only emit text.

## Output

Return your findings as **detailed prose** with URLs, dates, and key
quotes inline. Example shape (not a schema — just a suggestion):

```
Source 1: <URL>
  Published: <YYYY-MM-DD>
  Authors / publisher: ...
  Key quote: "..."
  Relevance: one sentence.

Source 2: <URL>
  ...
```

Cap the response at ~5 sources. Use primary sources where possible
(papers, advisories, RFCs, original author blog posts). If the topic is
time-sensitive, note publication dates prominently.

## Budget

You have a cap of 10 tool-use iterations (enforced by the orchestrator).
Use them sparingly — one `WebSearch` plus two or three `WebFetch` calls
usually suffice. Stop as soon as you have enough signal to cover the
request.

## Security context

You hold the OAuth token placeholder — the real token lives in the
egress proxy. Your outbound is gated by the proxy's "loose" tier (any
HTTPS), scoped to this phase alone because WebFetch legitimately needs
arbitrary hosts. Phase 2 (which processes your output as untrusted data)
runs under the "tight" tier — Anthropic-only — so there is no path from
web content → attacker-controlled host.

Input trust: this phase's input is the Owner's issue body (trusted).
Output trust: your prose is **untrusted** downstream and Phase 2 treats
it as data, not instructions.

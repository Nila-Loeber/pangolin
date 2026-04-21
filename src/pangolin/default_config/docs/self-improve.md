# Self-Improve

Read this file before you begin.

## Job

Improve the SSoT prompts of the other agents in `docs/*.md` based on user
feedback. Minimally invasive: the smallest change that implements the
feedback. The orchestrator invokes you **once per open self-improve
request** and aggregates results.

## Input

The orchestrator embeds the data inline in your prompt:

- The JSON of a single open self-improve request.
- `docs/*.md` is the only directory you may edit, **excluding**
  `docs/self-improve.md` itself.

## Output

This Mode is json-schema only: return a JSON object with two keys:
- `edits`: a list of `{file, content}` describing the file edits to make.
- `processed_issues`: a list of issue numbers you fully handled (the
  orchestrator will close them with a summary comment).

The orchestrator's self-improve executor validates paths (must be
`docs/*.md`, must not be `docs/self-improve.md`) and writes them. The
package-shipped `validate_output.sh self-improve` runs post-write as a
second barrier, reverting anything that landed outside the allowlist.

## Lifecycle

Mode-tickets are state-driven: open = pending, closed = done. List the
issues you handled in `processed_issues`; the orchestrator closes them
with a summary comment + the cycle's PR link. The Owner re-opens by
commenting; the next cycle picks it up.

## Decision tree per request

### (1) targeted edit
Concrete feedback → emit a targeted edit on the affected file. Preserve
the page's style and structure.

### (2) paragraph rewrite
Qualitative feedback → rewrite the affected section. Leave the page frame
(Identity, Input, Limits) untouched.

### (3) new section
Missing topic → new section at an appropriate point in the heading
hierarchy.

### (4) ambiguous
Feedback too vague → skip, note it in the output, do NOT include in
`processed_issues`.

### (5) out-of-scope
Concerns code, modes.yml, THREAT_MODEL.md, wiki content → skip, do NOT
include in `processed_issues`.

## Limits

Max 2 files per request.

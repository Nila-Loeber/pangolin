"""PR-feedback comment classifier.

Given an owner-authored PR comment body, decide which mode should address
it. Uses the same direct-json-schema pattern as inbox triage — shared
infrastructure (`run_direct`), a small dedicated schema, Sonnet for speed.

The invariant this enforces: every mode only handles comments applicable
to it. A code-fix request routes to software (writable: src/tests/scripts).
A wiki-page edit request routes to thinking (writable: wiki/notes). A
draft revision routes to writing (writable: drafts/content). No comment
ever escalates a mode's writable_paths — classification is an assignment,
not a permission widening.

A comment that doesn't describe an actionable change ("lgtm", "wontfix",
off-topic questions) returns "none" and the pr-feedback loop skips it.
"""

from __future__ import annotations

from pangolin.core import make_logger
from pangolin.modes import Mode

log = make_logger("classify")


_SYSTEM_PROMPT = """\
You classify a single owner-authored comment on a pangolin-authored PR.
Decide which mode (if any) should address it.

Modes and their writable scope:
- software — Edit code/tests/scripts (src/, tests/, scripts/). Choose when
  the comment asks for a code fix, new test, refactor, failing-build repair,
  or anything requiring executing tests.
- writing — Edit prose drafts (drafts/, content/). Choose when the
  comment asks for tone, phrasing, structure, or narrative changes to a
  draft. NOT for wiki reference pages.
- thinking — Edit wiki structure and analysis (wiki/, notes/). Choose
  when the comment asks for a TL;DR, cross-link, reorganization, or
  analysis revision to a wiki page or a thinking-mode note.
- none — The comment does not describe a concrete change the agent can
  make. Acknowledgements, questions, off-topic, already-done reports.
  Always choose "none" if the comment's ask spans multiple modes; the
  owner can narrow per follow-up comment.

Output a single JSON object with `mode` and a short `reason` (one sentence).
"""


def classify_comment(body: str, triage_mode: Mode, provider) -> tuple[str, str]:
    """Return (mode_name, reason) for this comment. mode_name is one of
    software|writing|thinking|none."""
    from pangolin.orchestrate import run_direct

    user = (
        f"--- COMMENT BODY ---\n{body}\n\n"
        f"--- TASK ---\nClassify. Emit one JSON object."
    )
    # The schema lives under "pr-feedback-classify"; we borrow the triage
    # mode's provider + model budget since triage + classify are siblings
    # (both "route a body to a mode" tasks, same speed/quality tier).
    result = run_direct(
        triage_mode, system=_SYSTEM_PROMPT, user=user,
        provider=provider, schema_name="pr-feedback-classify",
    )
    if not result:
        return ("none", "classifier returned empty")
    mode = result.get("mode", "none")
    reason = result.get("reason", "")
    if mode not in {"software", "writing", "thinking", "none"}:
        log(f"  classifier returned unknown mode {mode!r} — treating as 'none'")
        return ("none", f"unknown mode {mode!r}")
    return (mode, reason)

"""Tests for pr_feedback — the PR-comment → software-mode pickup loop.

The network-heavy code paths (gh calls, git checkout, agent spawn) are
exercised on the canary. Here we assert the pure input-filtering logic
that decides WHICH comments reach the agent — the security boundary.
"""
from __future__ import annotations

from pangolin.core import AGENT_MARKER
from pangolin import pr_feedback as PF


# ── _is_owner_comment: strict per-comment authorship + marker check ──

class TestIsOwnerComment:
    def test_owner_comment_passes(self):
        assert PF._is_owner_comment({
            "author": {"login": "nila"},
            "body": "please rename foo to bar",
        }) is True

    def test_bot_login_blocked(self):
        assert PF._is_owner_comment({
            "author": {"login": "github-actions[bot]"},
            "body": "CI passed",
        }) is False

    def test_agent_login_blocked(self):
        """Any login ending in -agent is treated as bot-origin."""
        assert PF._is_owner_comment({
            "author": {"login": "cycle-agent"},
            "body": "Addressed review comment",
        }) is False

    def test_agent_marker_blocks_even_with_human_login(self):
        """Belt-and-braces: if the owner ever posts via a PAT but the
        body carries AGENT_MARKER, treat as agent-origin."""
        assert PF._is_owner_comment({
            "author": {"login": "nila"},
            "body": f"{AGENT_MARKER}\nAddressed in abc1234",
        }) is False

    def test_missing_author_blocked(self):
        """Defensive: no author struct → don't trust it."""
        assert PF._is_owner_comment({"body": "hmm"}) is False


# ── _find_watermark: latest cycle-agent commit on the branch ──

class TestFindWatermark:
    def test_uses_latest_agent_commit(self):
        pr = {
            "createdAt": "2026-01-01T00:00:00Z",
            "commits": [
                {"committedDate": "2026-01-02T10:00:00Z",
                 "authors": [{"email": PF.AGENT_COMMIT_EMAIL}]},
                {"committedDate": "2026-01-03T11:00:00Z",
                 "authors": [{"email": PF.AGENT_COMMIT_EMAIL}]},
                {"committedDate": "2026-01-04T12:00:00Z",
                 "authors": [{"email": "nila@example.com"}]},  # ignored
            ],
        }
        assert PF._find_watermark(pr) == "2026-01-03T11:00:00Z"

    def test_fallback_to_createdAt_if_no_agent_commits(self):
        pr = {
            "createdAt": "2026-01-01T00:00:00Z",
            "commits": [
                {"committedDate": "2026-01-05T00:00:00Z",
                 "authors": [{"email": "other@example.com"}]},
            ],
        }
        assert PF._find_watermark(pr) == "2026-01-01T00:00:00Z"

    def test_empty_pr_data_safe(self):
        """No commits, no createdAt → empty string. Downstream filter
        ends up passing every non-empty createdAt — acceptable fallback
        when gh returns malformed data."""
        assert PF._find_watermark({}) == ""


# ── _pending_comments: watermark + owner-filter combined ──

class TestPendingComments:
    def _pr(self, watermark: str, comments: list[dict]) -> dict:
        return {
            "createdAt": watermark,
            "commits": [],  # forces fallback to createdAt
            "comments": comments,
        }

    def test_picks_owner_comment_after_watermark(self):
        pr = self._pr(
            "2026-01-01T00:00:00Z",
            [{
                "author": {"login": "nila"},
                "body": "please fix X",
                "createdAt": "2026-01-02T00:00:00Z",
            }],
        )
        pending = PF._pending_comments(pr)
        assert len(pending) == 1
        assert pending[0]["body"] == "please fix X"

    def test_drops_comment_before_watermark(self):
        """A comment from BEFORE the latest agent commit is already
        addressed — we don't re-process it."""
        pr = self._pr(
            "2026-01-03T00:00:00Z",
            [{
                "author": {"login": "nila"},
                "body": "stale ask",
                "createdAt": "2026-01-01T00:00:00Z",
            }],
        )
        assert PF._pending_comments(pr) == []

    def test_drops_bot_comment(self):
        pr = self._pr(
            "2026-01-01T00:00:00Z",
            [{
                "author": {"login": "github-actions[bot]"},
                "body": "CI status change",
                "createdAt": "2026-01-02T00:00:00Z",
            }],
        )
        assert PF._pending_comments(pr) == []

    def test_drops_our_own_progress_comment(self):
        """Our AGENT_MARKER-tagged progress reply must never trigger
        the next cycle. This is the self-loop guard."""
        pr = self._pr(
            "2026-01-01T00:00:00Z",
            [{
                "author": {"login": "nila"},
                "body": f"{AGENT_MARKER}\nAddressed review comment",
                "createdAt": "2026-01-02T00:00:00Z",
            }],
        )
        assert PF._pending_comments(pr) == []

    def test_returns_oldest_first(self):
        """Serialize: pick the earliest owner comment to address."""
        pr = self._pr(
            "2026-01-01T00:00:00Z",
            [
                {"author": {"login": "nila"}, "body": "B",
                 "createdAt": "2026-01-03T00:00:00Z"},
                {"author": {"login": "nila"}, "body": "A",
                 "createdAt": "2026-01-02T00:00:00Z"},
            ],
        )
        pending = PF._pending_comments(pr)
        assert [c["body"] for c in pending] == ["A", "B"]

    def test_mixes_authors_correctly(self):
        """Only the owner comments survive; their order is preserved."""
        pr = self._pr(
            "2026-01-01T00:00:00Z",
            [
                {"author": {"login": "nila"}, "body": "A",
                 "createdAt": "2026-01-02T00:00:00Z"},
                {"author": {"login": "github-actions[bot]"}, "body": "CI",
                 "createdAt": "2026-01-02T12:00:00Z"},
                {"author": {"login": "nila"}, "body": "B",
                 "createdAt": "2026-01-03T00:00:00Z"},
                {"author": {"login": "cycle-agent"}, "body": "done",
                 "createdAt": "2026-01-04T00:00:00Z"},
            ],
        )
        assert [c["body"] for c in PF._pending_comments(pr)] == ["A", "B"]

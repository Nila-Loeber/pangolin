"""Tests for the pr-feedback classifier + per-mode dispatch wiring.

The live Anthropic classification is covered by canary runs. Here we
assert:
  - the classifier schema exists and is well-formed
  - apply_writes_for_mode dispatches correctly per mode-schema
  - apply_writes_for_mode REJECTS out-of-scope writes per mode (security)
"""
from __future__ import annotations

import pytest

from pangolin.modes import SCHEMAS, Mode, load_modes
from pangolin.orchestrate import apply_writes_for_mode


class TestClassifierSchema:
    def test_schema_exists(self):
        assert "pr-feedback-classify" in SCHEMAS

    def test_schema_shape(self):
        s = SCHEMAS["pr-feedback-classify"]
        assert s["type"] == "object"
        assert "mode" in s["required"]
        enum = s["properties"]["mode"]["enum"]
        # Every mode in the enum must be either an existing mode name or "none".
        modes = load_modes()
        for m in enum:
            if m == "none":
                continue
            assert m in modes, f"classifier enum references unknown mode {m!r}"

    def test_enum_covers_the_expected_modes(self):
        """If the set of feedback-capable modes changes, update this
        test alongside the schema and the dispatcher in pr_feedback."""
        s = SCHEMAS["pr-feedback-classify"]
        assert set(s["properties"]["mode"]["enum"]) == {
            "software", "writing", "thinking", "none",
        }


class TestApplyWritesForMode:
    def _fake_mode(self, name: str, schema: str) -> Mode:
        # Minimal Mode for dispatch testing — apply_writes_for_mode only
        # reads .json_schema / .name.
        return Mode(
            name=name,
            description="test",
            network=False,
            code_execution=False,
            allowed_tools=[],
            denied_tools=[],
            readable_paths=["."],
            writable_paths=["."],
            gh_cli=False,
            autonomy="low",
            trust_level="trusted",
            provider="anthropic",
            model="claude-sonnet-4-6",
            execution="direct",
            container_runtime="runsc",
            json_schema=schema,
        )

    def test_writing_dispatches_to_drafts_policy(self, tmp_path, monkeypatch):
        """writing-mode writes must land under drafts/ or content/."""
        monkeypatch.chdir(tmp_path)
        import pangolin.orchestrate as orch
        monkeypatch.setattr(orch, "REPO", tmp_path)
        (tmp_path / "drafts").mkdir()
        written = apply_writes_for_mode(
            self._fake_mode("writing", "writing"),
            [{"path": "drafts/x.md", "content": "hi", "action": "create"}],
        )
        assert written == ["drafts/x.md"]

    def test_writing_rejects_wiki_path(self, tmp_path, monkeypatch):
        """Out-of-scope write (wiki/ under writing-mode) must be rejected."""
        monkeypatch.chdir(tmp_path)
        import pangolin.orchestrate as orch
        monkeypatch.setattr(orch, "REPO", tmp_path)
        (tmp_path / "wiki").mkdir()
        written = apply_writes_for_mode(
            self._fake_mode("writing", "writing"),
            [{"path": "wiki/x.md", "content": "hi", "action": "create"}],
        )
        assert written == []
        assert not (tmp_path / "wiki" / "x.md").exists()

    def test_thinking_allows_wiki_and_notes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import pangolin.orchestrate as orch
        monkeypatch.setattr(orch, "REPO", tmp_path)
        for d in ("wiki", "notes", "drafts"):
            (tmp_path / d).mkdir()
        written = apply_writes_for_mode(
            self._fake_mode("thinking", "thinking"),
            [
                {"path": "wiki/x.md", "content": "hi"},
                {"path": "notes/y.md", "content": "hi"},
                {"path": "drafts/z.md", "content": "hi"},
            ],
        )
        assert set(written) == {"wiki/x.md", "notes/y.md", "drafts/z.md"}

    def test_thinking_rejects_wiki_fragment(self, tmp_path, monkeypatch):
        """wiki/fragment/ is the quarantine zone — never writable by any
        mode (it's the raw untrusted research output)."""
        monkeypatch.chdir(tmp_path)
        import pangolin.orchestrate as orch
        monkeypatch.setattr(orch, "REPO", tmp_path)
        (tmp_path / "wiki").mkdir()
        written = apply_writes_for_mode(
            self._fake_mode("thinking", "thinking"),
            [{"path": "wiki/fragment/evil.md", "content": "hi"}],
        )
        assert written == []

    def test_thinking_rejects_schema_md(self):
        """wiki/SCHEMA.md is owner-curated structure — not agent-writable."""
        import tempfile, pathlib, pangolin.orchestrate as orch
        with tempfile.TemporaryDirectory() as d:
            dpath = pathlib.Path(d)
            (dpath / "wiki").mkdir()
            orig = orch.REPO
            orch.REPO = dpath
            try:
                written = apply_writes_for_mode(
                    self._fake_mode("thinking", "thinking"),
                    [{"path": "wiki/SCHEMA.md", "content": "mutated"}],
                )
                assert written == []
            finally:
                orch.REPO = orig

    def test_software_schema_not_dispatched(self):
        """software mode uses container tool-use, not direct writes —
        dispatcher should refuse the unsupported path."""
        with pytest.raises(ValueError, match="no write policy"):
            apply_writes_for_mode(
                self._fake_mode("software", "software"),
                [{"path": "src/x.py", "content": "print(1)"}],
            )

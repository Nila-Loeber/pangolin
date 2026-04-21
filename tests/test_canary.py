"""Unit tests for `pangolin.canary` — the `canary-update` command's pure
helpers. The gh-dispatching + `gh run watch` paths require a live GH API
and are validated on the canary itself."""
from __future__ import annotations

from pangolin import canary as C


class TestRefreshShim:
    def test_copies_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(C, "REPO", tmp_path)
        assert C._refresh_shim() is True
        dst = tmp_path / ".github" / "workflows" / "agent-cycle.yml"
        assert dst.exists()
        # The copy matches the package source byte-for-byte.
        from pangolin.paths import default_workflows_dir
        assert dst.read_bytes() == (default_workflows_dir() / "agent-cycle.yml").read_bytes()

    def test_no_op_when_identical(self, tmp_path, monkeypatch):
        """Second call on an already-current shim reports no change."""
        monkeypatch.setattr(C, "REPO", tmp_path)
        C._refresh_shim()
        assert C._refresh_shim() is False

    def test_updates_when_different(self, tmp_path, monkeypatch):
        """If the wiki's local copy drifts from the package, we overwrite
        and report True — this is the atomic-deploy path."""
        monkeypatch.setattr(C, "REPO", tmp_path)
        C._refresh_shim()
        dst = tmp_path / ".github" / "workflows" / "agent-cycle.yml"
        dst.write_text("# stale local edit\n")
        assert C._refresh_shim() is True
        assert "stale local edit" not in dst.read_text()


class TestScaffoldShipsSkill:
    """`pangolin init` drops the canary-update skill into `.claude/skills/`."""

    def test_init_scaffolds_skill_file(self, tmp_path):
        from pangolin.scaffold import init_repo
        init_repo(cwd=tmp_path)
        skill = tmp_path / ".claude" / "skills" / "canary-update" / "SKILL.md"
        assert skill.exists(), "canary-update skill not scaffolded"
        body = skill.read_text()
        assert "pangolin canary-update" in body
        assert "---" in body  # frontmatter present

    def test_package_ships_skill(self):
        """Regression guard: pyproject's package-data must keep shipping
        the skill file alongside the other default_config assets."""
        from pangolin.paths import default_claude_skills_dir
        skill = default_claude_skills_dir() / "canary-update" / "SKILL.md"
        assert skill.exists()
        assert "canary-update" in skill.read_text()

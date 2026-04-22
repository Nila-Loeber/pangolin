"""Regression tests for software.py helpers."""

from pangolin.software import _branch_for_task


class TestBranchForTask:
    def test_strips_colons(self):
        """Colons were breaking `git push` because refs with `:` get
        parsed as src:dst refspecs."""
        assert _branch_for_task(12, "software: add X") == "task/12-software-add-x"

    def test_strips_slashes(self):
        assert _branch_for_task(9, "feat/foo bar") == "task/9-feat-foo-bar"

    def test_collapses_runs(self):
        assert _branch_for_task(1, "a  b :: c") == "task/1-a-b-c"

    def test_truncates_long_titles(self):
        out = _branch_for_task(7, "x" * 200)
        assert out == "task/7-" + "x" * 40

    def test_empty_title(self):
        assert _branch_for_task(3, ":::") == "task/3"

    def test_only_uses_alnum_dash(self):
        import re
        for title in ["Hello, World!", "ä/ü:ß", "__foo__bar__"]:
            b = _branch_for_task(1, title)
            assert re.match(r"^task/1(-[a-z0-9-]+)?$", b), b


class TestVerifiedParser:
    def test_basic_single_path(self):
        from pangolin.software import _verified_paths
        assert _verified_paths("VERIFIED: scripts/foo.sh") == ["scripts/foo.sh"]

    def test_multiple_paths(self):
        from pangolin.software import _verified_paths
        out = _verified_paths("Files changed:\n- a.sh\n\nVERIFIED: scripts/a.sh, tests/b.py")
        assert out == ["scripts/a.sh", "tests/b.py"]

    def test_missing_footer(self):
        from pangolin.software import _verified_paths
        assert _verified_paths("I made the changes but forgot to list them.") == []

    def test_case_insensitive(self):
        from pangolin.software import _verified_paths
        assert _verified_paths("verified: x.sh") == ["x.sh"]

    def test_line_with_leading_spaces(self):
        from pangolin.software import _verified_paths
        assert _verified_paths("  VERIFIED: a, b") == ["a", "b"]

    def test_verified_word_in_prose_does_not_match(self):
        """Only a line whose non-colon prefix is exactly 'VERIFIED' counts;
        prose like 'The file was verified: ...' must not match."""
        from pangolin.software import _verified_paths
        assert _verified_paths("The file was verified: all good.") == []


class TestPRBodyMarker:
    def test_software_pr_body_carries_agent_marker(self):
        """software.py must wrap its PR body with AGENT_MARKER — otherwise
        pr_feedback.run() can't see the PR (it filters by AGENT_MARKER in
        body) and owner comments on software PRs are silently ignored.

        Observed on a chained smoke test: the PR was opened but cycle 2's
        pr-feedback phase reported `no owner comments awaiting response`
        because the software PR lacked the marker. Regression guard:
        assert software.py still calls wrap_agent_body on the PR body."""
        from pathlib import Path
        code = (Path(__file__).parent.parent / "src/pangolin/software.py").read_text()
        assert "wrap_agent_body" in code, (
            "software.py no longer uses wrap_agent_body for PR body — "
            "this silently breaks pr_feedback's ability to iterate on the PR"
        )
        # And the wrapped value is what gets passed to gh pr create
        assert "--body" in code
        # A stricter check: the line that constructs the PR body must
        # reference wrap_agent_body near it
        body_construct_idx = code.find("pr_body = wrap_agent_body")
        pr_create_idx = code.find('gh("pr", "create"')
        assert 0 < body_construct_idx < pr_create_idx, (
            "Expected `pr_body = wrap_agent_body(...)` before `gh pr create`"
        )

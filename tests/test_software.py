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

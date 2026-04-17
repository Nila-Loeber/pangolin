"""Security test suite for Sandburg. Structured by SFR."""
import subprocess, sys
from pathlib import Path
import pytest, yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from pangolin.modes import load_modes
from pangolin.tools import ToolConfig, ToolExecutor

def read(p): return p.read_text()
def modes(): return load_modes(REPO / "modes.yml")

class TestSfrTool:
    @pytest.mark.sfr("TOOL.1")
    def test_TOOL_1_research_no_tools(self):
        """Epic 9 phase-split: research (phase 2) is a direct agent with
        zero tools. The orchestrator runs phase 1 (WebSearch) in-process
        and passes results to phase 2 for summarisation."""
        m = modes()["research"]
        assert m.allowed_tools == []
        assert m.execution == "direct"
        assert m.json_schema == "research"
        assert m.network is False
        # writable_paths is intentionally empty — no write capability
        assert m.writable_paths == []
    @pytest.mark.sfr("TOOL.3")
    def test_TOOL_3_direct_agents_no_tools(self):
        for n in ("triage", "summary", "self-improve", "research"):
            assert modes()[n].allowed_tools == []
    @pytest.mark.sfr("TOOL.4")
    def test_TOOL_4_only_software_has_bash(self):
        for n, m in modes().items():
            if n == "software": assert "bash" in m.allowed_tools
            else: assert "bash" not in m.allowed_tools, f"{n} has bash"

class TestSfrFs:
    def _ex(self, r, w, t=None, c=False):
        return ToolExecutor(ToolConfig(REPO, r, w, c), t or {"read","write","glob"})
    @pytest.mark.sfr("FS.1")
    def test_FS_read_blocked(self):
        assert self._ex(["docs/"],["wiki/fragment/"]).execute("read",{"path":"modes.yml"}).is_error
    @pytest.mark.sfr("FS.1")
    def test_FS_read_allowed(self):
        assert not self._ex(["docs/"],["wiki/fragment/"]).execute("read",{"path":"docs/research-agent.md"}).is_error
    @pytest.mark.sfr("FS.2")
    def test_FS_write_blocked(self):
        assert self._ex(["docs/"],["wiki/fragment/"]).execute("write",{"path":"docs/evil.md","content":"x"}).is_error
    @pytest.mark.sfr("FS.2")
    def test_FS_write_allowed(self):
        r = self._ex(["wiki/"],["wiki/fragment/"]).execute("write",{"path":"wiki/fragment/u.md","content":"t"})
        assert not r.is_error; (REPO/"wiki/fragment/u.md").unlink(missing_ok=True)
    @pytest.mark.sfr("FS.1")
    def test_FS_traversal(self):
        ex = self._ex(["docs/"],["wiki/fragment/"])
        for p in ["../../../etc/passwd","/etc/passwd","docs/../../etc/passwd"]:
            assert ex.execute("read",{"path":p}).is_error
    @pytest.mark.sfr("FS.1")
    def test_FS_prefix_bug(self):
        assert self._ex(["notes/"],["notes/ideas/"]).execute("read",{"path":"notes_evil/x"}).is_error
    @pytest.mark.sfr("FS.1")
    def test_FS_bash_blocked(self):
        assert self._ex(["docs/"],["wiki/"],c=False).execute("bash",{"command":"id"}).is_error
    @pytest.mark.sfr("FS.1")
    def test_FS_bash_allowed(self):
        r = ToolExecutor(ToolConfig(REPO,["docs/"],["wiki/"],code_execution=True),{"bash"}).execute("bash",{"command":"echo ok"})
        assert not r.is_error and "ok" in r.content
    @pytest.mark.sfr("FS.1")
    def test_FS_disabled_tool(self):
        assert self._ex(["docs/"],["wiki/"],t={"glob"}).execute("read",{"path":"docs/research-agent.md"}).is_error
    @pytest.mark.sfr("FS.4")
    def test_FS_validator_removes_in_scope_invalid(self):
        """Validator removes a fragment that's in scope but has no frontmatter."""
        v = REPO/"wiki"/"fragment"/"pentest-v-no-frontmatter.md"
        v.parent.mkdir(parents=True, exist_ok=True)
        try:
            v.write_text("plain text, no yaml frontmatter at all\n")
            r = subprocess.run(["bash",str(REPO/"scripts/validate-output.sh"),"research"],capture_output=True,text=True,cwd=str(REPO))
            assert "missing frontmatter" in r.stderr
            assert not v.exists()
        finally: v.unlink(missing_ok=True)
    @pytest.mark.sfr("FS.4")
    def test_FS_validator_leaves_out_of_scope_untouched(self):
        """Validator does NOT touch files outside its mode's scope (e.g. .inbox-watermark from triage)."""
        # Modify a tracked out-of-scope file (use .ingest-watermark; saved + restored).
        wm = REPO/".inbox-watermark"
        original = wm.read_text() if wm.exists() else ""
        try:
            wm.write_text("2099-01-01T00:00:00Z\n")
            subprocess.run(["bash",str(REPO/"scripts/validate-output.sh"),"research"],capture_output=True,text=True,cwd=str(REPO))
            # research validator must NOT have reverted .inbox-watermark
            assert wm.read_text().startswith("2099"), "research validator wrongly reverted out-of-scope file"
        finally:
            wm.write_text(original)

class TestSfrTrifecta:
    @pytest.mark.sfr("TRIFECTA.1")
    def test_untrusted_no_read_no_code(self):
        for n, m in modes().items():
            if m.trust_level == "untrusted":
                assert "read" not in m.allowed_tools; assert not m.code_execution
    @pytest.mark.sfr("TRIFECTA.4")
    def test_validator_blocks_untrusted_code(self):
        import yaml, tempfile
        raw = yaml.safe_load((REPO/"modes.yml").read_text())
        raw["modes"]["research"]["code_execution"] = True
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(raw, f); f.flush()
            with pytest.raises(ValueError, match="untrusted.*code_execution"):
                load_modes(Path(f.name))

class TestSfrStruct:
    @pytest.mark.sfr("STRUCT.1")
    def test_direct_agents_have_schema(self):
        for n in ("triage","summary","self-improve","research"): assert modes()[n].json_schema
    @pytest.mark.sfr("STRUCT.3")
    def test_store_files_validated(self):
        assert "notes/ideas/" in read(REPO/"scripts/sandburg/orchestrate.py")
    @pytest.mark.sfr("STRUCT.2")
    def test_gh_repo_pinned(self):
        assert "GH_REPO" in read(REPO/"scripts/sandburg/orchestrate.py")

class TestSfrFlm:
    @pytest.mark.sfr("FLM.1")
    def test_FLM_1_python_enforcement(self):
        c = read(REPO/"scripts/sandburg/tools.py")
        assert "check_readable" in c and "PermissionError" in c
    @pytest.mark.sfr("INFRA.1")
    def test_INFRA_1_self_improve_blocked(self):
        assert "self-improve.md" in read(REPO/"scripts/sandburg/orchestrate.py")

class TestHardening:
    def test_harden_runner(self):
        for wf in (REPO/".github/workflows/agent-cycle.yml", REPO/".github/workflows/agent-software.yml"):
            assert "harden-runner" in read(wf)
    @pytest.mark.sfr("FLM.1")
    def test_iteration_limit(self):
        c = read(REPO/"scripts/sandburg/providers.py")
        assert "max_iterations" in c

class TestModesConsistency:
    @pytest.mark.sfr("MODE.1")
    def test_required_fields(self):
        for n, m in modes().items():
            for f in ("provider","model","execution","trust_level"):
                assert getattr(m, f), f"{n} missing {f}"
    @pytest.mark.sfr("TRIFECTA.5")
    def test_untrusted_have_quarantine(self):
        for n, m in modes().items():
            if m.trust_level == "untrusted": assert m.quarantine_output
    @pytest.mark.sfr("FLM.1")
    def test_invariants_enforced_at_load(self):
        """modes.py validates invariants at load time (geohot fix)."""
        import sandburg.modes as mm
        assert "_validate_invariants" in dir(mm) or "validate" in open(str(REPO/"scripts/sandburg/modes.py")).read()


class TestEpic9PhaseSplit:
    """Epic 9: research phase-split eliminates the lethal trifecta."""

    @pytest.mark.sfr("TRIFECTA.1")
    def test_research_phase2_no_trifecta(self):
        """Phase 2 (summariser) processes untrusted input but has no tools
        and no network — trifecta pillars (b) and (c) are missing."""
        m = modes()["research"]
        assert m.trust_level == "untrusted"
        assert m.network is False
        assert m.allowed_tools == []
        assert m.execution == "direct"
        assert not m.code_execution

    @pytest.mark.sfr("STRUCT.1")
    def test_research_schema_exists(self):
        from pangolin.modes import SCHEMAS
        s = SCHEMAS["research"]
        assert s["type"] == "object"
        assert "findings" in s["properties"]
        items = s["properties"]["findings"]["items"]
        for field in ("title", "source", "date", "summary", "why_relevant"):
            assert field in items["properties"]
            assert field in items["required"]


class TestEpic10OwnerTrigger:
    """Epic 10: agent-spawned issues are inert until owner comments."""

    def test_human_authored_issue_is_activated(self):
        from pangolin.orchestrate import _is_owner_activated
        issue = {"author": {"login": "nila"}, "comments": []}
        assert _is_owner_activated(issue) is True

    def test_bot_authored_issue_without_comment_is_inert(self):
        from pangolin.orchestrate import _is_owner_activated
        issue = {"author": {"login": "github-actions[bot]"}, "comments": []}
        assert _is_owner_activated(issue) is False

    def test_agent_authored_issue_without_comment_is_inert(self):
        from pangolin.orchestrate import _is_owner_activated
        issue = {"author": {"login": "cycle-agent"}, "comments": []}
        assert _is_owner_activated(issue) is False

    def test_bot_authored_with_owner_comment_is_activated(self):
        from pangolin.orchestrate import _is_owner_activated
        issue = {
            "author": {"login": "github-actions[bot]"},
            "comments": [{"author": {"login": "nila"}, "body": "go ahead"}],
        }
        assert _is_owner_activated(issue) is True

    def test_bot_authored_with_only_agent_marker_comment_stays_inert(self):
        from pangolin.orchestrate import _is_owner_activated, AGENT_MARKER
        issue = {
            "author": {"login": "github-actions[bot]"},
            "comments": [{"author": {"login": "nila"}, "body": f"{AGENT_MARKER}\nauto-comment"}],
        }
        assert _is_owner_activated(issue) is False


class TestSfrStruct4:
    """SFR.STRUCT.4: agent-emitted issue refs cross-checked against input set."""

    @pytest.mark.sfr("STRUCT.4")
    def test_STRUCT_4_report_processed_drops_non_eligible(self):
        from pangolin.tools import ToolConfig, ToolExecutor
        cfg = ToolConfig(repo_root=REPO, processed_eligible={5, 12})
        ex = ToolExecutor(cfg, {"report_processed"})
        result = ex.execute("report_processed", {"numbers": [5, 999, 12, 1000]})
        assert ex.processed == [5, 12]
        assert "rejected" in result.content
        assert "999" in result.content
        assert "1000" in result.content

    @pytest.mark.sfr("STRUCT.4")
    def test_STRUCT_4_report_processed_empty_eligible_drops_all(self):
        from pangolin.tools import ToolConfig, ToolExecutor
        cfg = ToolConfig(repo_root=REPO, processed_eligible=set())
        ex = ToolExecutor(cfg, {"report_processed"})
        ex.execute("report_processed", {"numbers": [1, 2, 3]})
        assert ex.processed == []


class TestSfrStruct4Inference:
    """SFR.STRUCT.4 inference layer: reject claims without observable side effect."""

    @pytest.mark.sfr("STRUCT.4")
    def test_research_inference_filter_drops_unbacked_claims(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        # Point inference at an empty fragment dir
        empty = tmp_path / "empty-repo"
        (empty / "wiki" / "fragment").mkdir(parents=True)
        monkeypatch.setattr(O, "REPO", empty)
        kept = O._research_inference_filter([5, 12])
        assert kept == []

    @pytest.mark.sfr("STRUCT.4")
    def test_research_inference_filter_keeps_backed_claims(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        repo = tmp_path / "repo"
        (repo / "wiki" / "fragment").mkdir(parents=True)
        (repo / "wiki" / "fragment" / "x.md").write_text(
            "---\ntitle: t\nsource_issue: 5\n---\nbody"
        )
        monkeypatch.setattr(O, "REPO", repo)
        kept = O._research_inference_filter([5, 12])
        assert kept == [5]

    @pytest.mark.sfr("STRUCT.4")
    def test_aggregate_inference_filter_drops_when_nothing_written(self):
        from pangolin.orchestrate import _aggregate_inference_filter
        assert _aggregate_inference_filter([1, 2], False, "thinking") == []
        assert _aggregate_inference_filter([1, 2], True, "thinking") == [1, 2]
        assert _aggregate_inference_filter([], False, "thinking") == []

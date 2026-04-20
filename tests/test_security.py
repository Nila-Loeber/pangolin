"""Security test suite for Pangolin. Structured by SFR."""
import subprocess, sys
from pathlib import Path
import pytest, yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from pangolin.modes import load_modes
from pangolin.paths import default_modes_yaml, validate_output_script
from pangolin.tools import ToolConfig, ToolExecutor

def read(p): return p.read_text()
def modes(): return load_modes()  # loads the package default (SSoT)

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
        # scope = src/, read README.md (exists, but outside scope) → must error.
        assert self._ex(["src/"],["wiki/fragment/"]).execute("read",{"path":"README.md"}).is_error
    @pytest.mark.sfr("FS.1")
    def test_FS_read_allowed(self):
        # scope = src/, read a file inside scope → must succeed.
        assert not self._ex(["src/"],["wiki/fragment/"]).execute("read",{"path":"src/pangolin/cli.py"}).is_error
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
            r = subprocess.run(["bash",str(validate_output_script()),"research"],capture_output=True,text=True,cwd=str(REPO))
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
            subprocess.run(["bash",str(validate_output_script()),"research"],capture_output=True,text=True,cwd=str(REPO))
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
        raw = yaml.safe_load(default_modes_yaml().read_text())
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
        assert "notes/ideas/" in read(REPO/"src/pangolin/orchestrate.py")
    @pytest.mark.sfr("STRUCT.2")
    def test_gh_repo_pinned(self):
        assert "GH_REPO" in read(REPO/"src/pangolin/orchestrate.py")

class TestSfrFlm:
    @pytest.mark.sfr("FLM.1")
    def test_FLM_1_python_enforcement(self):
        c = read(REPO/"src/pangolin/tools.py")
        assert "check_readable" in c and "PermissionError" in c
    @pytest.mark.sfr("INFRA.1")
    def test_INFRA_1_self_improve_blocked(self):
        assert "self-improve.md" in read(REPO/"src/pangolin/orchestrate.py")

class TestHardening:
    def test_workflow_is_thin_shim(self):
        """agent-cycle.yml is a thin shim — it calls `pangolin harden-egress`
        + `pangolin run`, nothing more. All orchestration logic lives in the
        pip package so updates are atomic across wiki repos."""
        wf = read(REPO/"src/pangolin/default_config/workflows/agent-cycle.yml")
        assert "pangolin harden-egress" in wf
        assert "pangolin run" in wf
        assert "pangolin-egress-proxy" in wf  # image pulled in setup step
        assert "harden-runner" not in wf
    def test_egress_hardening_lives_in_package(self):
        """The iptables + HTTPS_PROXY logic moved from the workflow yml into
        orchestrate.harden_egress() so shipping a new egress policy requires
        only a pip package bump."""
        c = read(REPO/"src/pangolin/orchestrate.py")
        assert "def harden_egress" in c
        assert "iptables" in c
        assert "HTTPS_PROXY" in c
    @pytest.mark.sfr("FLM.1")
    def test_iteration_limit(self):
        c = read(REPO/"src/pangolin/providers.py")
        assert "max_iterations" in c

class TestModesConsistency:
    @pytest.mark.sfr("MODE.1")
    def test_required_fields(self):
        for n, m in modes().items():
            for f in ("provider","model","execution","trust_level","egress"):
                assert getattr(m, f), f"{n} missing {f}"
    def test_egress_values(self):
        """Every mode declares an egress tier and it must be tight|loose."""
        for n, m in modes().items():
            assert m.egress in ("tight", "loose"), f"{n} has egress={m.egress!r}"
    def test_egress_invariant_enforced_at_load(self):
        """modes.py rejects invalid egress values at load time."""
        import tempfile
        raw = yaml.safe_load(default_modes_yaml().read_text())
        raw["modes"]["software"]["egress"] = "wide-open"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(raw, f); f.flush()
            with pytest.raises(ValueError, match="egress must be"):
                load_modes(Path(f.name))
    @pytest.mark.sfr("TRIFECTA.5")
    def test_untrusted_have_quarantine(self):
        for n, m in modes().items():
            if m.trust_level == "untrusted": assert m.quarantine_output
    @pytest.mark.sfr("FLM.1")
    def test_invariants_enforced_at_load(self):
        """modes.py validates invariants at load time (geohot fix)."""
        import pangolin.modes as mm
        assert "_validate_invariants" in dir(mm) or "validate" in open(str(REPO/"src/pangolin/modes.py")).read()


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


class TestMitmPhaseA:
    """MITM Phase A: real OAuth token lives only in the egress proxy.
    Agent containers get a placeholder and a proxy-CA mount so the claude
    CLI trusts the ssl-bumped cert for api.anthropic.com."""

    def test_agent_env_has_placeholder_not_real_token(self):
        """_base_docker_flags injects a placeholder into the agent container.
        The real CLAUDE_CODE_OAUTH_TOKEN only travels host → proxy env."""
        from pangolin.orchestrate import AGENT_PLACEHOLDER_TOKEN, _base_docker_flags
        # _base_docker_flags needs _PROXY_IP cached; patch it.
        import pangolin.orchestrate as O
        O._PROXY_IP = "10.0.0.99"
        flags = _base_docker_flags()
        joined = " ".join(flags)
        assert f"CLAUDE_CODE_OAUTH_TOKEN={AGENT_PLACEHOLDER_TOKEN}" in joined
        # The value is the fixed placeholder, not a read-from-host variable.
        # Regression guard: the old `-e CLAUDE_CODE_OAUTH_TOKEN` (no `=`)
        # would have leaked the real token into the container.
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in flags  # bare var-name pass-through
        O._PROXY_IP = None

    def test_agent_env_mounts_proxy_ca_readonly(self):
        """Agent containers mount the shared CA volume at /etc/pangolin:ro
        so NODE_EXTRA_CA_CERTS (baked into the image) resolves."""
        from pangolin.orchestrate import PROXY_CA_VOLUME, _base_docker_flags
        import pangolin.orchestrate as O
        O._PROXY_IP = "10.0.0.99"
        flags = _base_docker_flags()
        joined = " ".join(flags)
        assert f"{PROXY_CA_VOLUME}:/etc/pangolin:ro" in joined
        O._PROXY_IP = None

    def test_agent_images_set_node_extra_ca_certs(self):
        """Containerfile.llm + Containerfile.software set NODE_EXTRA_CA_CERTS
        pointing at the mount path."""
        for cf in ("Containerfile.llm", "Containerfile.software"):
            text = (REPO/cf).read_text()
            assert "NODE_EXTRA_CA_CERTS=/etc/pangolin/proxy-ca.crt" in text, f"{cf} missing"

    def test_egress_container_ssl_bumps_anthropic(self):
        """Containerfile.egress configures squid ssl-bump for Anthropic only
        and strips/re-injects the Authorization header."""
        cf = (REPO/"Containerfile.egress").read_text()
        assert "ssl-bump" in cf
        assert "anthropic_hosts" in cf
        # Strip global, inject for Anthropic.
        assert "request_header_access Authorization deny all" in cf
        assert 'request_header_add Authorization "Bearer ${ANTHROPIC_TOKEN}" anthropic_hosts' in cf
        # CA generated at runtime, not committed.
        assert "openssl genrsa" in cf
        assert "envsubst" in cf


class TestAtomicDeploy:
    """Package-as-SSoT: pip install updates behavior atomically across wikis."""

    def test_load_modes_defaults_to_package(self):
        """`load_modes()` with no args loads the package-shipped modes.yml —
        so wiki repos get new modes on pip upgrade without a sync step."""
        from pangolin.modes import load_modes
        m = load_modes()
        assert "software" in m and "research" in m

    def test_resolve_config_prefers_wiki_override(self, tmp_path, monkeypatch):
        """When the wiki repo contains a same-named file, it wins."""
        from pangolin import paths as pp
        monkeypatch.setattr("pangolin.core.REPO", tmp_path)
        (tmp_path / "docs").mkdir()
        override = tmp_path / "docs" / "writing-agent.md"
        override.write_text("custom writing ssot")
        assert pp.resolve_config("docs/writing-agent.md") == override

    def test_resolve_config_falls_back_to_package(self, tmp_path, monkeypatch):
        """When the wiki has no override, the package default is returned."""
        from pangolin import paths as pp
        monkeypatch.setattr("pangolin.core.REPO", tmp_path)
        resolved = pp.resolve_config("docs/writing-agent.md")
        assert "default_config" in str(resolved)
        assert resolved.exists()

    def test_modes_override_yml_deep_merges(self, tmp_path, monkeypatch):
        """modes.override.yml patches specific fields without forking the whole file."""
        from pangolin.modes import load_modes
        monkeypatch.setattr("pangolin.core.REPO", tmp_path)
        (tmp_path / "modes.override.yml").write_text(
            "modes:\n  software:\n    model: claude-haiku-4-5-20251001\n"
        )
        m = load_modes()
        assert m["software"].model == "claude-haiku-4-5-20251001"
        # Other fields preserved from package default
        assert m["software"].execution == "container"
        # Other modes untouched
        assert m["research"].trust_level == "untrusted"


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

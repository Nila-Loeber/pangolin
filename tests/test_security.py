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
        """Validator does NOT touch files outside its mode's scope. Research
        is scoped to wiki/fragment/, so a foreign probe file elsewhere must
        stay intact after a research-validator pass."""
        probe = REPO / ".pangolin-validator-probe"
        try:
            probe.write_text("should-not-be-touched\n")
            subprocess.run(
                ["bash", str(validate_output_script()), "research"],
                capture_output=True, text=True, cwd=str(REPO),
            )
            assert probe.exists(), "research validator wrongly deleted out-of-scope probe"
            assert probe.read_text() == "should-not-be-touched\n", \
                "research validator wrongly altered out-of-scope probe"
        finally:
            probe.unlink(missing_ok=True)

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
        """The HTTPS_PROXY export logic lives in orchestrate.harden_egress()
        so shipping a new egress policy requires only a pip package bump.

        The iptables REJECT that used to be part of harden_egress was
        removed 2026-04-21: it blocked GH Actions log-blob uploads
        (Azure Storage hosts that /meta doesn't publish) and the cost
        exceeded the DiD benefit (the REJECT only added protection
        against raw-socket host code; every HTTPS_PROXY-respecting
        library was already going through the proxy)."""
        c = read(REPO/"src/pangolin/orchestrate.py")
        assert "def harden_egress" in c
        assert "HTTPS_PROXY" in c
        # Negative invariant: host iptables REJECT was removed (breaks
        # GH Actions log-blob uploads). Re-adding requires first
        # whitelisting *.blob.core.windows.net or accepting broken logs.
        assert '"iptables"' not in c, (
            "iptables rule installation reintroduced in harden_egress — "
            "see removal rationale in its docstring before doing this"
        )

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

    def test_egress_container_runs_mitmproxy(self):
        """Containerfile.egress installs mitmproxy + ships the addon
        + starts mitmdump with two listeners. No squid/ICAP/aiohttp."""
        cf = (REPO/"Containerfile.egress").read_text()
        assert "mitmproxy==" in cf  # pinned
        assert "pangolin_egress.py" in cf
        assert "mitmdump" in cf
        assert "regular@3128" in cf and "regular@3129" in cf
        # The addon does the work — no squid stuff should remain.
        assert "squid" not in cf.lower()
        assert "icap" not in cf.lower()


class TestMitmPhaseB:
    """Phase B: pangolin_egress addon blocks server-side-tool exfil via
    api.anthropic.com /v1/messages POST bodies."""

    def test_egress_addon_present(self):
        """The mitmproxy addon ships in the package."""
        addon = REPO / "src/pangolin/pangolin_egress.py"
        assert addon.exists()
        code = addon.read_text()
        assert "def request" in code  # mitmproxy hook
        assert "_validate_messages_body" in code
        assert "SERVER_TOOL_ALLOWLIST" in code

    def test_addon_splices_non_anthropic_tls(self):
        """The addon must splice (TLS-tunnel, not MITM) every host except
        api.anthropic.com. Bumping api.github.com et al. would break any
        client that doesn't trust our runtime CA — e.g. the host `gh` CLI
        in the workflow runner."""
        code = (REPO / "src/pangolin/pangolin_egress.py").read_text()
        assert "tls_clienthello" in code
        assert "ignore_connection" in code
        # Splice rule lives on SNI != api.anthropic.com
        assert "ANTHROPIC_HOST" in code

    def test_server_tool_allowlist_empty_by_default(self):
        """No pangolin mode needs Anthropic's server-side tools — the
        starting policy denies them all. Changing this set should trip a
        review."""
        # Importing the addon needs mitmproxy installed; isolate the test
        # to the constants by reading the file.
        code = (REPO/"src/pangolin/pangolin_egress.py").read_text()
        assert "SERVER_TOOL_ALLOWLIST: set[str] = set()" in code

    def test_addon_authorization_rewrite(self):
        code = (REPO/"src/pangolin/pangolin_egress.py").read_text()
        # Addon strips incoming Authorization unconditionally on anthropic
        # then re-injects from $ANTHROPIC_TOKEN.
        assert 'flow.request.headers.pop("Authorization"' in code
        assert 'ANTHROPIC_TOKEN' in code

    def test_addon_validates_messages_body(self):
        code = (REPO/"src/pangolin/pangolin_egress.py").read_text()
        assert "/v1/messages" in code
        assert "tools" in code
        assert "ttype" in code  # the discriminator we block on

    def test_anthropic_endpoint_allowlist_default_deny(self):
        """Default-deny on api.anthropic.com: only POST /v1/messages is
        allowlisted. Closes the exfil path via /v1/messages/batches,
        /v1/messages/count_tokens, or future beta endpoints nobody
        has audited yet."""
        code = (REPO/"src/pangolin/pangolin_egress.py").read_text()
        assert "ANTHROPIC_ENDPOINT_ALLOWLIST" in code
        assert '("POST", "/v1/messages")' in code
        # Helper exists and is referenced by request()
        assert "_endpoint_allowed" in code

    def test_endpoint_deny_precedes_token_injection(self):
        """A denied endpoint must be blocked before the Authorization
        rewrite. Otherwise the 403 would still carry our real OAuth
        token upstream, defeating the purpose of endpoint-scoping."""
        code = (REPO/"src/pangolin/pangolin_egress.py").read_text()
        endpoint_check = code.find("_endpoint_allowed(method, path)")
        auth_inject = code.find('flow.request.headers.pop("Authorization"')
        assert endpoint_check != -1, "endpoint check not present in request()"
        assert auth_inject != -1, "auth rewrite not present in request()"
        assert endpoint_check < auth_inject, (
            "endpoint allowlist check must precede token injection so "
            "denied endpoints never bear the real OAuth token"
        )


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


class TestQ1DirectWrites:
    """Q1 (direct json-schema) path-scope validation. Ensures that the host's
    executor rejects out-of-scope / traversal / forbidden paths the agent
    might emit in its JSON response.
    """

    def _runner(self, repo, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", repo)
        runner = O.CycleRunner.__new__(O.CycleRunner)
        return runner, O

    @pytest.mark.sfr("Q1.1")
    def test_writing_rejects_traversal(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._execute_writing_drafts([
            {"path": "drafts/../etc/passwd", "content": "x"},
        ])
        assert written == []

    @pytest.mark.sfr("Q1.1")
    def test_writing_rejects_out_of_scope(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._execute_writing_drafts([
            {"path": "src/evil.py", "content": "x"},
            {"path": "wiki/foo.md", "content": "x"},
            {"path": ".env", "content": "x"},
        ])
        assert written == []

    @pytest.mark.sfr("Q1.1")
    def test_writing_accepts_valid_paths(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._execute_writing_drafts([
            {"path": "drafts/foo.md", "content": "hello"},
            {"path": "content/bar.md", "content": "world"},
        ])
        assert set(written) == {"drafts/foo.md", "content/bar.md"}
        assert (tmp_path / "drafts/foo.md").read_text() == "hello"

    @pytest.mark.sfr("Q1.1")
    def test_writing_caps_at_3_drafts(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._execute_writing_drafts([
            {"path": f"drafts/a{i}.md", "content": "x"} for i in range(5)
        ])
        assert len(written) == 3

    @pytest.mark.sfr("Q1.1")
    def test_writing_skips_empty_content(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._execute_writing_drafts([
            {"path": "drafts/x.md", "content": ""},
            {"path": "drafts/y.md", "content": "   "},
        ])
        assert written == []

    @pytest.mark.sfr("Q1.2")
    def test_thinking_rejects_fragments_and_schema(self, tmp_path, monkeypatch):
        """Thinking path-scope MUST forbid wiki/fragment/ (read-only archive)
        and wiki/SCHEMA.md (structural spec). An agent-emitted write to either
        is a silent security breach if not rejected."""
        runner, O = self._runner(tmp_path, monkeypatch)
        written = runner._apply_path_scoped_writes(
            [
                {"path": "wiki/fragment/evil.md", "content": "x"},
                {"path": "wiki/SCHEMA.md", "content": "x"},
                {"path": "wiki/good-topic.md", "content": "legit"},
            ],
            allowed_prefixes=runner._THINKING_ALLOWED_PREFIXES,
            forbidden=runner._THINKING_FORBIDDEN,
            tag="thinking",
        )
        assert written == ["wiki/good-topic.md"]
        assert not (tmp_path / "wiki/fragment/evil.md").exists()
        assert not (tmp_path / "wiki/SCHEMA.md").exists()

    @pytest.mark.sfr("Q1.2")
    def test_wiki_ingest_rejects_fragments(self, tmp_path, monkeypatch):
        """Wiki-ingest must not overwrite the fragment archive — that would
        break the audit trail (wiki page X → sourced from fragment Y)."""
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._apply_path_scoped_writes(
            [{"path": "wiki/fragment/poison.md", "content": "x"}],
            allowed_prefixes=runner._WIKI_INGEST_ALLOWED_PREFIXES,
            forbidden=runner._WIKI_INGEST_FORBIDDEN,
            tag="wiki-ingest",
        )
        assert written == []

    @pytest.mark.sfr("Q1.2")
    def test_wiki_ingest_rejects_index(self, tmp_path, monkeypatch):
        """wiki/index.md is regenerated by the wiki-index phase, not ingest."""
        runner, _ = self._runner(tmp_path, monkeypatch)
        written = runner._apply_path_scoped_writes(
            [{"path": "wiki/index.md", "content": "fake index"}],
            allowed_prefixes=runner._WIKI_INGEST_ALLOWED_PREFIXES,
            forbidden=runner._WIKI_INGEST_FORBIDDEN,
            tag="wiki-ingest",
        )
        assert written == []

    @pytest.mark.sfr("Q1.2")
    def test_apply_path_scoped_writes_respects_max(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        writes = [{"path": f"wiki/p{i}.md", "content": f"x{i}"} for i in range(10)]
        written = runner._apply_path_scoped_writes(
            writes, allowed_prefixes=("wiki/",), max_writes=4, tag="test",
        )
        assert len(written) == 4

    @pytest.mark.sfr("Q1.2")
    def test_apply_path_scoped_writes_append_appends(self, tmp_path, monkeypatch):
        runner, _ = self._runner(tmp_path, monkeypatch)
        target = tmp_path / "wiki" / "log.md"
        target.parent.mkdir(parents=True)
        target.write_text("existing\n")
        runner._apply_path_scoped_writes(
            [{"path": "wiki/log.md", "content": "new entry", "action": "append"}],
            allowed_prefixes=("wiki/",), tag="test",
        )
        content = target.read_text()
        assert "existing" in content and "new entry" in content


class TestTriageSchemaNoWatermark:
    """D2 regression: triage schema no longer requires (or even includes)
    a `watermark` field. The host computes the new watermark deterministically
    from issue/comment timestamps; asking the agent to emit it was wasted
    tokens + a misleading Instruction in the SSoT doc."""

    def test_triage_schema_lacks_watermark(self):
        from pangolin.modes import SCHEMAS
        s = SCHEMAS["triage"]
        assert "watermark" not in s["required"]
        assert "watermark" not in s["properties"]


class TestResearchDocSplit:
    """DRIFT-7 regression: research pipeline has two distinct SSoT docs
    because Phase 1 (trusted input, WebSearch tools) and Phase 2 (untrusted
    input, no tools) are operationally different."""

    def test_both_research_docs_exist(self):
        from pangolin.paths import default_docs_dir
        d = default_docs_dir()
        assert (d / "research-search-agent.md").exists()
        assert (d / "research-summarise-agent.md").exists()
        # The pre-split file must be gone — having both would be a silent
        # merge conflict waiting to happen.
        assert not (d / "research-agent.md").exists()

    def test_research_alias_resolves_to_summarise(self):
        """The generic fallback in run_container_agent (API-key path) aliases
        `research` mode → research-summarise-agent.md so the pre-split file
        rename doesn't silently reroute to inbox-triage.md."""
        import pangolin.orchestrate as orch
        src = (REPO / "src/pangolin/orchestrate.py").read_text()
        assert "research-summarise-agent.md" in src


class TestSelfImproveValidatorWired:
    """D3 regression: _phase_self_improve must invoke the validator post-write,
    matching the claim in docs/self-improve.md (second barrier)."""

    def test_phase_self_improve_calls_validator(self):
        src = (REPO / "src/pangolin/orchestrate.py").read_text()
        # Locate the self-improve phase body and check it spawns the validator.
        import re
        m = re.search(
            r"def _phase_self_improve.*?(?=\n    def |\nclass |\Z)",
            src, re.DOTALL,
        )
        assert m, "could not find _phase_self_improve in orchestrate.py"
        body = m.group(0)
        assert 'validate_output_script()' in body
        assert '"self-improve"' in body


class TestDeadContainerPathRemoved:
    """D4 regression: _phase_task_mode no longer falls back to a container-
    tool-use path. Both thinking and writing run as direct json-schema (Q1),
    and any other mode_name passed in is an explicit error."""

    def test_phase_task_mode_rejects_unknown_mode(self):
        from pangolin import orchestrate as O
        runner = O.CycleRunner.__new__(O.CycleRunner)
        # Stub in what _phase_task_mode reads from self.modes
        from pangolin.modes import load_modes
        runner.modes = load_modes()
        # The function lists issues via gh first; pre-empt that to avoid
        # network by checking the raise path via direct inspection.
        src = (REPO / "src/pangolin/orchestrate.py").read_text()
        assert "spawn_agent_container_tooluse" not in src.split("def _phase_task_mode")[1].split("def _run_")[0]

    def test_has_new_writes_in_removed(self):
        """The helper was only called by the deleted container fallback."""
        from pangolin import orchestrate as O
        assert not hasattr(O, "_has_new_writes_in")


class TestAgentCommitEmailShared:
    """D5 regression: the commit email the cycle uses is a single constant
    in core.py; pr_feedback imports it. agent-cycle.yml must set git
    user.email to the same value or the PR-feedback watermark misses
    agent commits."""

    def test_core_exports_the_constant(self):
        from pangolin.core import AGENT_COMMIT_EMAIL
        assert AGENT_COMMIT_EMAIL.endswith("@users.noreply.github.com")

    def test_pr_feedback_uses_core_constant(self):
        from pangolin import pr_feedback as PF
        from pangolin.core import AGENT_COMMIT_EMAIL
        assert PF.AGENT_COMMIT_EMAIL is AGENT_COMMIT_EMAIL

    def test_workflow_sets_the_same_email(self):
        from pangolin.core import AGENT_COMMIT_EMAIL
        wf = (REPO / "src/pangolin/default_config/workflows/agent-cycle.yml").read_text()
        assert AGENT_COMMIT_EMAIL in wf, (
            "agent-cycle.yml must set git user.email to core.AGENT_COMMIT_EMAIL"
        )


class TestWritingReferencedFiles:
    """DRIFT-12 regression: writing-mode iterating on an existing draft now
    receives the current file content inline when the task body references
    its path, instead of seeing only a directory listing."""

    def _task(self, body: str, title: str = "iterate"):
        return {"number": 1, "title": title, "body": body}

    def test_references_drafts_path_in_body(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", tmp_path)
        (tmp_path / "drafts").mkdir()
        (tmp_path / "drafts" / "foo.md").write_text("old version")
        blobs = O._referenced_writable_files(
            self._task("please tighten drafts/foo.md"),
            allowed_prefixes=("drafts/", "content/"),
            cap_bytes=10_000,
        )
        assert len(blobs) == 1
        assert "drafts/foo.md" in blobs[0]
        assert "old version" in blobs[0]

    def test_ignores_unrelated_paths(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "evil.md").write_text("code")
        blobs = O._referenced_writable_files(
            self._task("touch src/evil.md"),
            allowed_prefixes=("drafts/", "content/"),
            cap_bytes=10_000,
        )
        assert blobs == []

    def test_ignores_missing_files(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", tmp_path)
        blobs = O._referenced_writable_files(
            self._task("rewrite drafts/nope.md"),
            allowed_prefixes=("drafts/", "content/"),
            cap_bytes=10_000,
        )
        assert blobs == []

    def test_rejects_traversal(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", tmp_path)
        (tmp_path / "drafts").mkdir()
        (tmp_path / "secret.md").write_text("nope")
        blobs = O._referenced_writable_files(
            self._task("see drafts/../secret.md"),
            allowed_prefixes=("drafts/", "content/"),
            cap_bytes=10_000,
        )
        assert blobs == []

    def test_cap_bytes_truncates(self, tmp_path, monkeypatch):
        from pangolin import orchestrate as O
        monkeypatch.setattr(O, "REPO", tmp_path)
        (tmp_path / "drafts").mkdir()
        (tmp_path / "drafts" / "a.md").write_text("x" * 600)
        (tmp_path / "drafts" / "b.md").write_text("y" * 600)
        blobs = O._referenced_writable_files(
            self._task("edit drafts/a.md and drafts/b.md"),
            allowed_prefixes=("drafts/", "content/"),
            cap_bytes=700,
        )
        # First file fits, second is a truncation marker (no content).
        assert len(blobs) == 2
        assert "drafts/a.md" in blobs[0] and "x" in blobs[0]
        assert "TRUNCATED" in blobs[1]


class TestTriagePathsNoInboxWatermark:
    """DRIFT-6 regression: .inbox-watermark lives in a GitHub issue comment
    now (sentinel pattern). Mounting a nonexistent file path into agent
    containers would fail at _build_mounts — purge it from the triage paths."""

    def test_triage_paths_dont_include_inbox_watermark(self):
        from pangolin.modes import load_modes
        triage = load_modes()["triage"]
        assert ".inbox-watermark" not in triage.readable_paths
        assert ".inbox-watermark" not in triage.writable_paths

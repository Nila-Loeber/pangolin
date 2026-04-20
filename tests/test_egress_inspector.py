"""Tests for Phase-B inspector (src/pangolin/egress_inspector.py).

Two layers:
  1. Pure-Python unit tests of the policy function `validate_body()`.
  2. Live aiohttp integration: run the inspector against a mock upstream,
     verify allowed requests are forwarded and blocked requests get 403.
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web

from pangolin import egress_inspector as EI


# ── Unit: validate_body ────────────────────────────────────────────────

class TestPolicy:
    def test_empty_body_allowed(self):
        assert EI.validate_body(b"") == (True, "")

    def test_non_json_allowed(self):
        """Non-JSON bodies (e.g. streaming events) aren't blocked."""
        ok, _ = EI.validate_body(b"not json")
        assert ok

    def test_no_tools_allowed(self):
        ok, _ = EI.validate_body(json.dumps({
            "model": "claude-sonnet-4-6", "max_tokens": 100,
            "messages": [{"role": "user", "content": "hi"}],
        }).encode())
        assert ok

    def test_custom_tools_allowed(self):
        """Tools with {name, description, input_schema} are custom — fine."""
        ok, _ = EI.validate_body(json.dumps({
            "tools": [{
                "name": "Read",
                "description": "read a file",
                "input_schema": {"type": "object"},
            }],
        }).encode())
        assert ok

    def test_server_side_web_fetch_blocked(self):
        """The scary one — attacker-supplied URL fetch via Anthropic."""
        ok, reason = EI.validate_body(json.dumps({
            "tools": [{"type": "web_fetch_20250910", "name": "web_fetch"}],
        }).encode())
        assert not ok
        assert "web_fetch_20250910" in reason

    def test_server_side_web_search_blocked(self):
        ok, reason = EI.validate_body(json.dumps({
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        }).encode())
        assert not ok
        assert "web_search_20250305" in reason

    def test_server_side_code_execution_blocked(self):
        ok, reason = EI.validate_body(json.dumps({
            "tools": [{"type": "code_execution_20250522"}],
        }).encode())
        assert not ok
        assert "code_execution_20250522" in reason

    def test_mixed_custom_and_server_tools_block_on_first_server(self):
        ok, reason = EI.validate_body(json.dumps({
            "tools": [
                {"name": "Read", "description": "ok",
                 "input_schema": {"type": "object"}},
                {"type": "web_fetch_20250910"},
            ],
        }).encode())
        assert not ok
        assert "tools[1]" in reason

    def test_allowlist_honors_override(self, monkeypatch):
        monkeypatch.setattr(EI, "SERVER_TOOL_ALLOWLIST", {"text_editor_20250728"})
        ok, _ = EI.validate_body(json.dumps({
            "tools": [{"type": "text_editor_20250728"}],
        }).encode())
        assert ok


# ── Integration: the inspector in front of a mock upstream ──────────────

@pytest.fixture
async def upstream(aiohttp_server):
    """Stand-in for api.anthropic.com — echoes the incoming Authorization."""
    async def handle(request):
        body = await request.read()
        return web.json_response({
            "path": request.path_qs,
            "method": request.method,
            "auth": request.headers.get("Authorization", ""),
            "body_bytes": len(body),
        })
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handle)
    return await aiohttp_server(app)


@pytest.fixture
async def inspector(aiohttp_server, upstream, monkeypatch):
    """Run the inspector, pointed at the mock upstream."""
    monkeypatch.setenv(
        "INSPECTOR_UPSTREAM", f"http://{upstream.host}:{upstream.port}"
    )
    # Reimport to pick up the env var at module load.
    import importlib
    import pangolin.egress_inspector
    importlib.reload(pangolin.egress_inspector)
    from pangolin.egress_inspector import make_app
    return await aiohttp_server(make_app())


class TestForwarding:
    async def test_benign_request_is_forwarded(self, inspector, aiohttp_client):
        """Ordinary /v1/messages POST with custom tools reaches the upstream."""
        client = await aiohttp_client(inspector)
        r = await client.post(
            "/v1/messages?beta=true",
            headers={"Authorization": "Bearer injected-by-squid"},
            json={
                "tools": [{
                    "name": "Read", "description": "x",
                    "input_schema": {"type": "object"},
                }],
            },
        )
        assert r.status == 200
        body = await r.json()
        assert body["path"] == "/v1/messages?beta=true"
        assert body["auth"] == "Bearer injected-by-squid"
        assert body["body_bytes"] > 0

    async def test_server_tool_is_blocked_with_403(self, inspector, aiohttp_client):
        client = await aiohttp_client(inspector)
        r = await client.post(
            "/v1/messages",
            headers={"Authorization": "Bearer anything"},
            json={"tools": [{"type": "web_fetch_20250910"}]},
        )
        assert r.status == 403
        body = await r.json()
        assert body["error"]["type"] == "pangolin_policy_blocked"
        assert "web_fetch_20250910" in body["error"]["message"]

    async def test_non_messages_endpoint_not_inspected(self, inspector, aiohttp_client):
        """Other paths (e.g. /v1/messages/count_tokens) skip policy — custom
        tools with server types might appear in count-tokens payloads but
        they're not actually executed there."""
        client = await aiohttp_client(inspector)
        r = await client.post(
            "/v1/messages/count_tokens",
            json={"tools": [{"type": "web_fetch_20250910"}]},
        )
        assert r.status == 200  # forwarded, not blocked

    async def test_get_is_not_inspected(self, inspector, aiohttp_client):
        client = await aiohttp_client(inspector)
        r = await client.get("/v1/messages")
        assert r.status == 200  # GET never has a tools-bearing body

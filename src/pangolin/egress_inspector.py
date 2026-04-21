"""Phase-B inspector: reverse-proxy for api.anthropic.com that blocks
server-side tool exfil.

Phase A (already merged) closed the OAuth-token leak by ssl-bumping and
injecting the Authorization header at squid. A compromised agent can
still POST to /v1/messages (within the bumped TLS) with attacker-supplied
`tools` entries of the form `{"type": "web_fetch_<date>"}` — Anthropic
fulfils the fetch server-side and leaks data to any URL the attacker
names. The hostname allowlist can't see this since it's all inside the
one allowed domain (api.anthropic.com).

Squid routes anthropic-bound plaintext (post-ssl-bump) to this service
via `cache_peer 127.0.0.1 parent 9000 originserver`. This service parses
the JSON body of every /v1/messages POST, rejects any tool entry with
a `type` field (server-side tools), and forwards legitimate requests to
api.anthropic.com over a fresh TLS connection.

Deliberately-empty server-tool allowlist today: no pangolin mode uses
Anthropic's server-side tools. The CLI's WebSearch/WebFetch used by
research-phase-1 are CLIENT-SIDE tools (handled by the CLI itself),
not the `type`-flagged server tools. If that ever changes, add the
specific `type` values to SERVER_TOOL_ALLOWLIST below.

Runs inside pangolin-egress-proxy alongside squid; owned by the same
container, started by start-proxy.sh before exec-ing squid.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from aiohttp import ClientSession, ClientTimeout, TCPConnector, web

LISTEN_HOST = os.environ.get("INSPECTOR_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("INSPECTOR_LISTEN_PORT", "9000"))
UPSTREAM = os.environ.get("INSPECTOR_UPSTREAM", "https://api.anthropic.com")
# Max body size we'll buffer for inspection. /v1/messages requests with
# large contexts can be big but are bounded by the API's own limits;
# refuse anything obviously oversized to avoid OOM on the proxy.
MAX_BODY_BYTES = int(os.environ.get("INSPECTOR_MAX_BODY_BYTES", str(8 * 1024 * 1024)))

# Server-side tool `type` values this proxy permits. Empty today — every
# pangolin mode uses either custom tools ({name, description, input_schema})
# or client-side CLI tools (handled by the claude CLI, not via the API).
# Add entries like {"text_editor_20250728"} if a future mode legitimately
# needs a specific Anthropic server-side tool.
SERVER_TOOL_ALLOWLIST: set[str] = set()

# Headers we never forward upstream regardless of what squid/agent sends.
# `Host` is rewritten by the client library; `Connection`/`Proxy-*` are
# hop-by-hop and would confuse the upstream TLS session.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
}

log = logging.getLogger("pangolin-inspector")


def validate_body(body_bytes: bytes) -> tuple[bool, str]:
    """Return (allowed, reason). Non-JSON and non-tool-bearing requests pass.

    Rejects any tool entry that has a `type` field — those are Anthropic's
    server-side tools (web_fetch, web_search, code_execution, ...), which
    open the api.anthropic.com-as-exfil vector.
    """
    if not body_bytes:
        return True, ""
    try:
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Non-JSON body (shouldn't happen on /v1/messages but don't block it).
        return True, ""
    if not isinstance(body, dict):
        return True, ""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return True, ""
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        ttype = tool.get("type")
        if ttype is None:
            continue  # custom tool ({name, description, input_schema}) — fine
        if ttype in SERVER_TOOL_ALLOWLIST:
            continue
        return False, f"server-side tool type={ttype!r} blocked (tools[{i}])"
    return True, ""


def _is_messages_post(method: str, path: str) -> bool:
    """Only /v1/messages POSTs carry a `tools` array worth inspecting."""
    if method != "POST":
        return False
    # Match /v1/messages, /v1/messages?beta=true, etc.
    return path.split("?", 1)[0].rstrip("/") == "/v1/messages"


async def _forward(request: web.Request, session: ClientSession) -> web.Response:
    """Copy the request to Anthropic (with original headers) and return the
    full response back to squid.

    Was StreamResponse with chunked transfer-encoding — that confused squid 6.9
    when forwarding via cache_peer originserver: squid would close the
    transport before aiohttp finished writing headers. Buffering the entire
    body and returning a Response with explicit Content-Length avoids the
    HTTP/1.1 chunked-encoding handshake entirely.
    """
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP
    }
    # Re-read the body we already consumed for validation.
    body = request["validated_body"]
    upstream_url = UPSTREAM.rstrip("/") + request.path_qs
    async with session.request(
        request.method, upstream_url, headers=fwd_headers, data=body,
        allow_redirects=False,
    ) as upstream:
        upstream_body = await upstream.read()
        # Drop any framing-related headers — aiohttp will set Content-Length
        # itself based on the buffered body.
        framing = {"transfer-encoding", "content-length", "content-encoding"}
        resp_headers = {
            k: v for k, v in upstream.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() not in framing
        }
        return web.Response(
            status=upstream.status, headers=resp_headers, body=upstream_body,
        )


async def handle(request: web.Request) -> web.StreamResponse:
    # Always read body, enforcing size limit.
    body = await request.read()
    if len(body) > MAX_BODY_BYTES:
        log.warning("oversized body (%d > %d), refusing", len(body), MAX_BODY_BYTES)
        return web.json_response(
            {"error": "pangolin-inspector: request body too large"},
            status=413,
        )
    request["validated_body"] = body
    if _is_messages_post(request.method, request.path_qs):
        ok, reason = validate_body(body)
        if not ok:
            log.warning("BLOCK %s %s: %s", request.method, request.path, reason)
            return web.json_response(
                {"error": {"type": "pangolin_policy_blocked", "message": reason}},
                status=403,
            )
    return await _forward(request, request.app["session"])


async def _on_startup(app: web.Application) -> None:
    app["session"] = ClientSession(
        timeout=ClientTimeout(total=600),
        connector=TCPConnector(limit=100),
    )


async def _on_cleanup(app: web.Application) -> None:
    await app["session"].close()


def make_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app.router.add_route("*", "/{tail:.*}", handle)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("INSPECTOR_LOG_LEVEL", "INFO"),
        format="[pangolin-inspector] %(message)s",
        stream=sys.stderr,
    )
    log.info("listening on %s:%d, upstream=%s", LISTEN_HOST, LISTEN_PORT, UPSTREAM)
    web.run_app(
        make_app(), host=LISTEN_HOST, port=LISTEN_PORT,
        access_log=None, print=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

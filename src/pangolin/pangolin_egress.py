"""pangolin egress proxy — mitmproxy addon.

Two listeners:
  3128 tight  — hostname allowlist (Anthropic+GitHub+PyPI+etc.) +
                api.anthropic.com endpoint allowlist (default-deny) +
                Authorization injection +
                /v1/messages body inspection (server-side-tool block)
  3129 loose  — any HTTPS host. Used only by research-search WebFetch.

Phase A: the real OAuth token lives only in this proxy's environment as
$ANTHROPIC_TOKEN. The agent container ships a placeholder; the addon
strips whatever Authorization header arrived and injects the real one
for anthropic-bound requests. /proc/self/environ in the agent therefore
never holds the token.

Phase B: api.anthropic.com is additionally restricted at the endpoint
level — default-deny, with POST /v1/messages the only allowlisted
entry (ANTHROPIC_ENDPOINT_ALLOWLIST). Denied endpoints get 403 *before*
token injection, so the real OAuth token never bears a request to an
un-audited endpoint. For allowlisted endpoints whose body may carry
tools[], the body is parsed and any entry with a `type` field — i.e.
an Anthropic server-side tool such as `web_fetch_*` — is blocked with
a synthetic 403. Custom tools (`{name, description, input_schema}`)
pass through. SERVER_TOOL_ALLOWLIST starts empty: no pangolin mode
legitimately uses Anthropic-server-side tools today.

Fail-secure: any unhandled exception in the addon kills the request
(mitmproxy default). With mitmproxy on the only egress path and
iptables forcing all outbound through it, kill = blocked.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from mitmproxy import http, tls

log = logging.getLogger("pangolin-egress")

TIGHT_PORT = int(os.environ.get("PANGOLIN_TIGHT_PORT", "3128"))
LOOSE_PORT = int(os.environ.get("PANGOLIN_LOOSE_PORT", "3129"))

# Hostnames the tight tier allows. Loose tier allows everything (used only
# by research-search-mode WebFetch which intentionally fetches arbitrary
# web pages).
TIGHT_ALLOWLIST: set[str] = {
    "api.anthropic.com",
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
    "ghcr.io",
    "pkg-containers.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "gvisor.dev",
    "storage.googleapis.com",
    "dl-cdn.alpinelinux.org",
    "registry.npmjs.org",
}

ANTHROPIC_HOST = "api.anthropic.com"
ANTHROPIC_TOKEN = os.environ.get("ANTHROPIC_TOKEN", "")

# Server-side tool `type` values the policy permits. Empty today — every
# pangolin mode uses either custom tools (which have name/description/
# input_schema, no `type` discriminator) or client-side CLI tools
# (handled by the claude CLI process, not via the API). Add specific
# `type` strings here if a future mode legitimately needs an Anthropic
# server-side tool.
SERVER_TOOL_ALLOWLIST: set[str] = set()

# Endpoints permitted on api.anthropic.com. Default-deny: any
# (method, path) combination not in this set gets a 403 *before* we
# inject the real OAuth token. Pangolin's only legitimate Anthropic
# traffic today is the messages API; batch/count_tokens/beta paths are
# unused and therefore not trusted. Adding an entry here is a
# security-relevant change (expands the token-bearing endpoint
# surface) and must be reviewed.
ANTHROPIC_ENDPOINT_ALLOWLIST: set[tuple[str, str]] = {
    ("POST", "/v1/messages"),
}

# Where mitmproxy keeps its CA (configured via --set confdir below).
CA_CONFDIR = Path("/etc/mitmproxy")
SHARED_CA_PATH = Path("/shared/proxy-ca.crt")


def _is_messages_post(method: str, path: str) -> bool:
    if method != "POST":
        return False
    return path.split("?", 1)[0].rstrip("/").endswith("/v1/messages")


def _endpoint_allowed(method: str, path: str) -> bool:
    """Default-deny match against ANTHROPIC_ENDPOINT_ALLOWLIST.

    Path is normalised: query string stripped, trailing slash stripped.
    Suffix-match on `endswith` because api.anthropic.com paths may be
    served under arbitrary prefixes in future (versioned hosts, org-
    scoped paths); we match on the canonical last segment.
    """
    normalized = path.split("?", 1)[0].rstrip("/")
    return any(
        method == m and normalized.endswith(suffix)
        for m, suffix in ANTHROPIC_ENDPOINT_ALLOWLIST
    )


def _block(reason: str) -> http.Response:
    body = json.dumps(
        {"error": {"type": "pangolin_policy_blocked", "message": reason}}
    ).encode()
    return http.Response.make(
        403, body, {"Content-Type": "application/json"}
    )


class PangolinEgress:
    def running(self) -> None:
        """Called once after mitmproxy has bound listeners. The CA file is
        guaranteed to exist by now — copy it to the shared volume so agent
        containers can mount it as NODE_EXTRA_CA_CERTS."""
        ca = CA_CONFDIR / "mitmproxy-ca-cert.pem"
        if ca.exists():
            SHARED_CA_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ca, SHARED_CA_PATH)
            SHARED_CA_PATH.chmod(0o644)
            log.info("CA published to %s", SHARED_CA_PATH)
        else:
            log.error("FATAL: %s missing — agent containers will fail TLS handshake", ca)

    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        """Decide MITM-bump vs TLS-splice per connection, by SNI + listener.

        We only need to MITM api.anthropic.com (Phase A header injection +
        Phase B body inspection). Every other host gets spliced (raw TLS
        tunnel) so the client doesn't have to trust our runtime CA.

        - loose port  → always splice (research-search WebFetch goes anywhere)
        - tight port + SNI == api.anthropic.com → bump (default, no action)
        - tight port + SNI in TIGHT_ALLOWLIST → splice
        - tight port + SNI not in allowlist → fall through to MITM, gets
          a 403 in request() (or TLS-fails on clients that don't trust our
          CA — either way it's blocked)
        """
        local_port = data.context.client.sockname[1]
        sni = data.client_hello.sni or ""

        if local_port == LOOSE_PORT:
            data.ignore_connection = True
            return

        if sni in TIGHT_ALLOWLIST and sni != ANTHROPIC_HOST:
            data.ignore_connection = True

    def request(self, flow: http.HTTPFlow) -> None:
        """Only api.anthropic.com (and disallowed-host MITM survivors) reach
        this hook — everything else was spliced in tls_clienthello."""
        host = flow.request.pretty_host
        method = flow.request.method
        path = flow.request.path

        if host != ANTHROPIC_HOST:
            log.warning(
                "BLOCK tight %s %s — host not in allowlist",
                method, flow.request.url,
            )
            flow.response = _block(f"host {host!r} not in tight allowlist")
            return

        # Endpoint-level default-deny. Runs *before* the Authorization
        # rewrite so denied endpoints never bear the real OAuth token.
        if not _endpoint_allowed(method, path):
            log.warning(
                "BLOCK tight %s %s — endpoint not in anthropic allowlist",
                method, flow.request.url,
            )
            flow.response = _block(
                f"endpoint {method} {path.split('?', 1)[0]!r} not in anthropic allowlist"
            )
            return

        # Authorization rewrite. Strip whatever the agent sent (placeholder),
        # inject the real token from proxy env. Agent containers never see it.
        flow.request.headers.pop("Authorization", None)
        if ANTHROPIC_TOKEN:
            flow.request.headers["Authorization"] = f"Bearer {ANTHROPIC_TOKEN}"

        # Phase B body inspection for messages-family endpoints.
        if _is_messages_post(method, path):
            ok, reason = _validate_messages_body(flow.request.content or b"")
            if not ok:
                log.warning("BLOCK %s — %s", flow.request.url, reason)
                flow.response = _block(reason)
                return

        log.info("PASS tight %s %s", method, flow.request.url)


def _validate_messages_body(body: bytes) -> tuple[bool, str]:
    """Reject any POST /v1/messages whose tools[] has a server-side type."""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        # Unparseable JSON — let upstream decide (anthropic will reject
        # malformed). We only block known-bad shapes.
        return True, ""
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return True, ""
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        ttype = tool.get("type")
        if ttype is None:
            continue  # custom tool — has name/description/input_schema
        if ttype in SERVER_TOOL_ALLOWLIST:
            continue
        return False, f"server-side tool type={ttype!r} blocked (tools[{i}])"
    return True, ""


addons = [PangolinEgress()]

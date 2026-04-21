"""Phase-B inspector as an ICAP REQMOD service.

Replaces the previous HTTP reverse-proxy implementation
(egress_inspector.py) which couldn't be wired into squid via cache_peer:
ssl-bump pins the bumped TLS connection to the origin server, and PINNED
forwarding is selected preferentially over any cache_peer. squid logged
`stopAndDestroy: for pinned connection failure` on every inner POST.

ICAP is squid's native content-inspection protocol. It sits inside the
forwarding pipeline rather than alongside it, so pinning is irrelevant.
This server implements REQMOD only (request modification before forward):

  squid → REQMOD this request → us → 204 (allow) | 403 (deny) | 200 (modify)

For pangolin's policy:
- /v1/messages POST bodies are parsed; if `tools` contains any entry with
  a `type` field (Anthropic server-side tools like `web_fetch_*`,
  `web_search_*`, `code_execution_*`), respond 403 with a JSON error.
- Custom tools (`{name, description, input_schema}`) pass through with 204.
- Anything else (non-/v1/messages, GET, no body) → 204.

Stdlib only — keeps the proxy image lean and avoids the aiohttp pin-rot
that already bit us once.
"""

from __future__ import annotations

import json
import logging
import os
import socketserver
import sys
from typing import Iterable

LISTEN_HOST = os.environ.get("ICAP_LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("ICAP_LISTEN_PORT", "1344"))
ICAP_SERVICE_PATH = os.environ.get("ICAP_SERVICE_PATH", "/inspector")
MAX_BODY_BYTES = int(os.environ.get("ICAP_MAX_BODY_BYTES", str(8 * 1024 * 1024)))

# Server-side tool `type` values the policy permits. Empty today — every
# pangolin mode uses either custom tools ({name, description, input_schema})
# or client-side CLI tools (handled by the claude CLI, not via the API).
SERVER_TOOL_ALLOWLIST: set[str] = set()

log = logging.getLogger("pangolin-icap")


# ── Validation ── (shared shape with the previous implementation) ────────

def _is_messages_post(method: str, target: str) -> bool:
    if method != "POST":
        return False
    return target.split("?", 1)[0].rstrip("/").endswith("/v1/messages")


def validate_body(body: bytes) -> tuple[bool, str]:
    """Return (allowed, reason). Allowed=True passes the body unchanged.

    Mirrors the previous egress_inspector.validate_body so policy doesn't
    drift between the two implementations.
    """
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeDecodeError):
        return True, ""  # unparseable → let upstream decide; we only
        # block known-bad shapes, not malformed JSON.
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return True, ""
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            continue
        ttype = tool.get("type")
        if ttype is None:
            continue  # custom tool — has name/description/input_schema instead
        if ttype in SERVER_TOOL_ALLOWLIST:
            continue
        return False, f"server-side tool type={ttype!r} blocked (tools[{i}])"
    return True, ""


# ── ICAP framing ──────────────────────────────────────────────────────────

ICAP_VERSION = "ICAP/1.0"
SERVER_NAME = "pangolin-egress-icap/1.0"


def _read_line(rfile) -> bytes:
    line = rfile.readline()
    if not line:
        raise EOFError("client disconnected")
    return line


def _read_headers(rfile) -> dict[str, str]:
    headers: dict[str, str] = {}
    while True:
        line = _read_line(rfile)
        s = line.rstrip(b"\r\n")
        if not s:
            break
        if b":" not in s:
            continue
        k, _, v = s.partition(b":")
        headers[k.decode("ascii", errors="replace").strip().lower()] = (
            v.decode("ascii", errors="replace").strip()
        )
    return headers


def _read_chunked_body(rfile, max_bytes: int) -> bytes:
    """Read an HTTP/1.1 chunked-transfer-encoding body. Cap to max_bytes.

    ICAP uses chunked encoding for the encapsulated body — even when the
    upstream HTTP request didn't.
    """
    out = bytearray()
    while True:
        size_line = _read_line(rfile).rstrip(b"\r\n")
        # squid may send "<hex>; ieof" or "<hex>". Strip extensions.
        size_token = size_line.split(b";", 1)[0].strip()
        try:
            size = int(size_token, 16)
        except ValueError:
            break
        if size == 0:
            # Read trailing CRLF (and potential trailers — none expected).
            _ = rfile.readline()
            break
        chunk = rfile.read(size)
        out += chunk
        if len(out) > max_bytes:
            raise ValueError(f"body exceeds {max_bytes} bytes")
        # Each chunk ends with CRLF.
        _ = rfile.readline()
    return bytes(out)


def _parse_encapsulated(value: str) -> dict[str, int]:
    """Parse `Encapsulated: req-hdr=0, req-body=412` into {section: offset}."""
    out: dict[str, int] = {}
    for entry in value.split(","):
        entry = entry.strip()
        if "=" not in entry:
            continue
        k, _, v = entry.partition("=")
        try:
            out[k.strip()] = int(v.strip())
        except ValueError:
            continue
    return out


# ── ICAP responses ────────────────────────────────────────────────────────

def _icap_response_lines(status: int, reason: str, extra: Iterable[str] = ()) -> bytes:
    head = f"{ICAP_VERSION} {status} {reason}\r\n"
    headers = [
        f"Server: {SERVER_NAME}",
        "Connection: close",
        *extra,
    ]
    return (head + "\r\n".join(headers) + "\r\n\r\n").encode("ascii")


def _icap_204_no_content() -> bytes:
    """Allow as-is. Squid forwards the original request unchanged."""
    return _icap_response_lines(204, "No Content", ["Encapsulated: null-body=0"])


def _icap_403_blocked(reason: str) -> bytes:
    """Block. Encapsulated response replaces the request — the agent
    receives this as the API response."""
    body_obj = {
        "error": {
            "type": "pangolin_policy_blocked",
            "message": reason,
        }
    }
    body = json.dumps(body_obj).encode("utf-8")
    res_hdr = (
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"\r\n"
    )
    body_chunk = (
        f"{len(body):x}\r\n".encode("ascii") + body + b"\r\n0\r\n\r\n"
    )
    encapsulated = f"Encapsulated: res-hdr=0, res-body={len(res_hdr)}"
    head = (
        f"{ICAP_VERSION} 200 OK\r\n"
        f"Server: {SERVER_NAME}\r\n"
        "Connection: close\r\n"
        f"{encapsulated}\r\n"
        "\r\n"
    ).encode("ascii")
    return head + res_hdr + body_chunk


PREVIEW_BYTES = int(os.environ.get("ICAP_PREVIEW_BYTES", "4096"))


def _icap_options() -> bytes:
    """Service description for squid's OPTIONS probe.

    Preview: PREVIEW_BYTES — squid sends only that many body bytes upfront
    and waits for our 100-Continue or 204/200. For typical /v1/messages
    bodies the `tools` array fits in the first few KB. For most modes the
    body is much smaller than the preview cap → ICAP can decide on the
    full body in one round trip.
    """
    extra = [
        "Methods: REQMOD",
        f"Service: {SERVER_NAME}",
        "Max-Connections: 100",
        "Options-TTL: 3600",
        "Allow: 204",
        f"Preview: {PREVIEW_BYTES}",
        "Encapsulated: null-body=0",
    ]
    return _icap_response_lines(200, "OK", extra)


# ── Request dispatch ──────────────────────────────────────────────────────

class _Handler(socketserver.StreamRequestHandler):
    def handle(self):  # noqa: D401
        log.debug("connection from %s", self.client_address)
        try:
            self._dispatch()
        except (EOFError, ConnectionResetError, BrokenPipeError) as exc:
            log.debug("client disconnected: %s", exc)
        except Exception as exc:  # last-resort guard
            log.exception("icap handler crashed: %s", exc)

    def _dispatch(self):
        request_line = _read_line(self.rfile).rstrip(b"\r\n")
        log.info("REQ %s", request_line.decode("ascii", errors="replace"))
        try:
            method, target, version = request_line.decode("ascii").split(" ", 2)
        except ValueError:
            return
        if version != ICAP_VERSION:
            log.warning("rejecting unsupported ICAP version: %s", version)
            return
        icap_headers = _read_headers(self.rfile)
        if method == "OPTIONS":
            self.wfile.write(_icap_options())
            log.info("OPTIONS → 200")
            return
        if method != "REQMOD":
            self.wfile.write(_icap_response_lines(405, "Method Not Allowed"))
            return

        encap = _parse_encapsulated(icap_headers.get("encapsulated", ""))
        # Read encapsulated req-hdr (until we hit either req-body offset or EOF).
        # ICAP spec: the body of the encapsulation arrives as chunked transfer
        # AFTER the req-hdr block has been read off the wire.
        # All sections come back-to-back; offsets in Encapsulated header are
        # relative to the start of the encapsulated payload.
        req_hdr_bytes = b""
        if "req-hdr" in encap and "req-body" in encap:
            req_hdr_len = encap["req-body"] - encap["req-hdr"]
            req_hdr_bytes = self.rfile.read(req_hdr_len)
        elif "req-hdr" in encap and "null-body" in encap:
            # No body to read.
            req_hdr_len = encap["null-body"] - encap["req-hdr"]
            req_hdr_bytes = self.rfile.read(req_hdr_len)
        # Parse the embedded request line.
        first = req_hdr_bytes.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        try:
            http_method, http_target, _http_version = first.split(" ", 2)
        except ValueError:
            self.wfile.write(_icap_204_no_content())
            return

        # Read encapsulated body (chunked) if present.
        body = b""
        if "req-body" in encap:
            try:
                body = _read_chunked_body(self.rfile, MAX_BODY_BYTES)
            except ValueError as exc:
                log.warning("oversized body: %s", exc)
                self.wfile.write(_icap_403_blocked(str(exc)))
                return

        # Apply policy.
        if not _is_messages_post(http_method, http_target):
            log.info("PASS %s %s (not /v1/messages POST) → 204", http_method, http_target)
            self.wfile.write(_icap_204_no_content())
            return
        ok, reason = validate_body(body)
        if ok:
            log.info("PASS %s %s (body OK, %d bytes) → 204", http_method, http_target, len(body))
            self.wfile.write(_icap_204_no_content())
            return
        log.warning("BLOCK %s %s: %s", http_method, http_target, reason)
        self.wfile.write(_icap_403_blocked(reason))


class _ThreadedICAPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ICAP_LOG_LEVEL", "INFO"),
        format="[pangolin-icap] %(message)s",
        stream=sys.stderr,
    )
    log.info("listening on %s:%d, service=%s", LISTEN_HOST, LISTEN_PORT, ICAP_SERVICE_PATH)
    server = _ThreadedICAPServer((LISTEN_HOST, LISTEN_PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Restricted authenticated HTTP bridge from Docker to loopback-only Ollama."""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BRIDGE_PORT = 11435
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 11434
CONNECT_TIMEOUT_SECONDS = 5
UPSTREAM_TIMEOUT_SECONDS = 180
MAX_REQUEST_BODY = 2 * 1024 * 1024
MAX_RESPONSE_BODY = 16 * 1024 * 1024
ALLOWED = {("GET", "/api/tags"), ("POST", "/api/show"), ("POST", "/api/chat")}

LOG = logging.getLogger("lingoveil-ollama-bridge")


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], token: str) -> None:
        super().__init__(address, BridgeHandler)
        self.token = token


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.info("%s - %s", self.client_address[0], fmt % args)

    def _json_error(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, expected)

    def _handle(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment or parsed.path != self.path:
            self._json_error(403, "endpoint denied")
            return
        if (self.command, self.path) not in ALLOWED:
            self._json_error(403, "endpoint denied")
            return
        if not self._authorized():
            self._json_error(401, "authentication required")
            return

        body = b""
        if self.command == "POST":
            media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                self._json_error(415, "Content-Type must be application/json")
                return
            if self.headers.get("Transfer-Encoding"):
                self._json_error(400, "chunked request bodies are not supported")
                return
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length) if raw_length is not None else -1
            except ValueError:
                length = -1
            if length < 0:
                self._json_error(411, "valid Content-Length required")
                return
            if length > MAX_REQUEST_BODY:
                self._json_error(413, "request body too large")
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._json_error(400, "incomplete request body")
                return

        connection: http.client.HTTPConnection | None = None
        try:
            connection = http.client.HTTPConnection(
                UPSTREAM_HOST, UPSTREAM_PORT, timeout=CONNECT_TIMEOUT_SECONDS
            )
            headers = {"Host": f"{UPSTREAM_HOST}:{UPSTREAM_PORT}"}
            if self.command == "POST":
                headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
            connection.request(self.command, self.path, body=body or None, headers=headers)
            if connection.sock is not None:
                connection.sock.settimeout(UPSTREAM_TIMEOUT_SECONDS)
            response = connection.getresponse()
            response_body = response.read(MAX_RESPONSE_BODY + 1)
            if len(response_body) > MAX_RESPONSE_BODY:
                self._json_error(502, "Ollama response too large")
                return
            self.send_response(response.status)
            content_type = response.getheader("Content-Type", "application/json")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)
        except (OSError, TimeoutError, socket.timeout, http.client.HTTPException) as exc:
            LOG.warning("Ollama upstream unavailable: %s", type(exc).__name__)
            self._json_error(502, "Ollama upstream unavailable")
        finally:
            if connection is not None:
                connection.close()

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_PATCH = _handle
    do_OPTIONS = _handle


def read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    return value


def read_bind_address(path: Path) -> str:
    value = path.read_text(encoding="ascii").strip()
    if value in {"", "0.0.0.0", "127.0.0.1", "::"}:
        raise ValueError("Unsafe or missing bridge bind address")
    socket.inet_aton(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind-address-file", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=BRIDGE_PORT)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    address = read_bind_address(args.bind_address_file)
    token = read_secret(args.token_file)
    server = BridgeServer((address, args.port), token)
    LOG.info("listening on %s:%d; upstream is %s:%d", address, args.port, UPSTREAM_HOST, UPSTREAM_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

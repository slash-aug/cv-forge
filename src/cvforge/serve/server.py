"""The HTTP shell around App: binds 127.0.0.1 and turns requests into Request objects."""
from __future__ import annotations

import errno
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from cvforge.serve.app import MAX_BODY, App, Request, Response

HOST = "127.0.0.1"
INTERNAL_ERROR = (b'{"error": "internal", "message": "Internal error"}')


class PortInUse(Exception):
    def __init__(self, port: int):
        super().__init__(f"port {port} is already in use")
        self.port = port


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, address, handler, app: App):
        self.app = app
        super().__init__(address, handler)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def _serve(self) -> None:
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            length = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            length = 0
        body = self.rfile.read(min(length, MAX_BODY + 1)) if length else b""
        request = Request(self.command, parts.path, query, headers, body)
        try:
            response = self.server.app.handle(request)
        except Exception as exc:  # noqa: BLE001 - never leak details of personal data to the client or the log
            print(f"internal error: {self.command} {parts.path} {type(exc).__name__}", file=sys.stderr)
            response = Response(500, INTERNAL_ERROR)
        self._send(response, drain=max(0, length - len(body)))

    def _send(self, response: Response, drain: int) -> None:
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers.items():
            self.send_header(name, value)
        if drain:
            # the unread rest of an oversized body would corrupt a kept-alive connection
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_HEAD = _serve

    def log_message(self, format, *args):
        pass

    def log_request(self, code="-", size="-"):
        path = urlsplit(self.path).path
        print(f"{self.command} {path} {code}", file=sys.stderr)


def make_server(app: App, port: int) -> ThreadingHTTPServer:
    try:
        return _Server((HOST, port), _Handler, app)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise PortInUse(port) from None
        raise

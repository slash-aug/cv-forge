import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from cvforge.cli import main
from cvforge.serve import server
from cvforge.serve.app import App, Request, Response
from cvforge.serve.token import load_or_create


@pytest.fixture
def running(tmp_path):
    token = load_or_create(tmp_path)
    app = App(tmp_path, token, 0)
    httpd = server.make_server(app, 0)
    app.port = httpd.server_address[1]  # the Host check wants the real port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, token, app
    httpd.shutdown()
    httpd.server_close()


def _get(httpd, path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}{path}")
    if token:
        req.add_header("X-CVForge-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_server_round_trip(running):
    httpd, token, _ = running
    assert httpd.server_address[0] == "127.0.0.1"
    status, body = _get(httpd, "/health", token)
    assert status == 200
    assert json.loads(body)["version"] == "1"
    assert _get(httpd, "/health")[0] == 401


def test_second_bind_is_port_in_use(running):
    httpd, _, app = running
    with pytest.raises(server.PortInUse) as exc:
        server.make_server(app, httpd.server_address[1])
    assert exc.value.port == httpd.server_address[1]


def test_show_token_prints_and_exits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    assert main(["serve", "--show-token"]) == 0
    assert capsys.readouterr().out.strip() == load_or_create(tmp_path)


def test_serve_reports_port_taken(tmp_path, monkeypatch, capsys, running):
    httpd, _, _ = running
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    port = httpd.server_address[1]
    assert main(["serve", "--port", str(port)]) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert err[-1] == f"cv-forge server already running on port {port}"


class _FakeHttpd:
    def __init__(self, port):
        self.server_address = ("127.0.0.1", port)

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass


@pytest.fixture
def fake_serve(tmp_path, monkeypatch):
    """cmd_serve up to serve_forever, with no socket: the bind returns a fake that stops at once."""
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CVFORGE_SERVE_PORT", raising=False)
    monkeypatch.setattr(server, "make_server", lambda app, port: _FakeHttpd(port))
    return tmp_path


def test_serve_start_does_not_print_the_token(fake_serve, capsys):
    assert main(["serve"]) == 0
    out, err = capsys.readouterr()
    assert "pairing token: run cvforge serve --show-token" in out.splitlines()
    pairing = load_or_create(fake_serve)
    assert pairing not in out and pairing not in err


def test_serve_on_the_default_port_does_not_warn(fake_serve, capsys):
    assert main(["serve"]) == 0
    assert "only connects to port 47321" not in capsys.readouterr().err


def test_serve_on_another_port_warns_about_the_extension(fake_serve, capsys):
    assert main(["serve", "--port", "47400"]) == 0
    out, err = capsys.readouterr()
    assert "the browser extension only connects to port 47321" in err.splitlines()
    assert "http://127.0.0.1:47400" in out


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_serve_rejects_ports_outside_1_to_65535(fake_serve, capsys, port):
    assert main(["serve", "--port", port]) == 1
    assert capsys.readouterr().err.strip() == f"port must be between 1 and 65535, got {port}"


def test_log_omits_query(running, capsys):
    httpd, token, _ = running
    _get(httpd, "/match?url=secret", token)
    err = capsys.readouterr().err
    assert "secret" not in err
    assert "/match" in err


def test_handler_failure_is_generic_500(tmp_path, capsys):
    class Boom(App):
        def handle(self, request):
            raise RuntimeError("Ana Exemplo private detail")

    boom = Boom(tmp_path, "t", 0)
    httpd = server.make_server(boom, 0)
    boom.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(httpd, "/health?x=secret", "t")
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert status == 500
    assert json.loads(body) == {"error": "internal", "message": "Internal error"}
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "private" not in err and "secret" not in err


def test_request_parts_reach_the_app(tmp_path):
    seen = {}

    class Spy(App):
        def handle(self, request: Request) -> Response:
            seen["req"] = request
            return Response(200, b"{}")

    spy = Spy(tmp_path, "t", 0)
    httpd = server.make_server(spy, 0)
    spy.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/answers?a=1&a=2&b=",
            data=b"hello", method="POST", headers={"X-CVForge-Token": "t"})
        urllib.request.urlopen(req, timeout=5).read()
    finally:
        httpd.shutdown()
        httpd.server_close()
    got = seen["req"]
    assert (got.method, got.path, got.query, got.body) == ("POST", "/answers", {"a": "1", "b": ""}, b"hello")
    assert got.headers["x-cvforge-token"] == "t"


def _raw(httpd, payload: bytes, shutdown_write=False) -> bytes:
    import socket

    with socket.create_connection(("127.0.0.1", httpd.server_address[1]), timeout=5) as sock:
        sock.sendall(payload)
        if shutdown_write:
            sock.shutdown(socket.SHUT_WR)
        chunks = []
        try:
            while chunk := sock.recv(65536):
                chunks.append(chunk)
        except OSError:
            pass
        return b"".join(chunks)


def _status(reply: bytes) -> str:
    return reply.split(b"\r\n", 1)[0].decode("latin-1")


def test_error_paths_before_parsing_answer_cleanly(running, capsys):
    httpd, _, _ = running
    long_line = b"GET /" + b"a" * 70000 + b"?q=secret HTTP/1.1\r\nHost: x\r\n\r\n"
    assert " 414 " in _status(_raw(httpd, long_line))
    assert " 400 " in _status(_raw(httpd, b"GET / HTTP/1.1 extra\r\n\r\n"))
    err = capsys.readouterr().err
    assert "Traceback" not in err and "AttributeError" not in err
    assert "secret" not in err


def test_unparseable_path_is_400_without_echo(running, capsys):
    httpd, token, _ = running
    reply = _raw(httpd, b"GET http://[bad/x?q=secret HTTP/1.1\r\nHost: x\r\n\r\n")
    assert " 400 " in _status(reply)
    assert b'"bad-request"' in reply and b"secret" not in reply
    err = capsys.readouterr().err
    assert "Traceback" not in err and "secret" not in err
    assert _get(httpd, "/health", token)[0] == 200


@pytest.mark.parametrize("header", [b"Content-Length: abc", b"Content-Length: -5",
                                    b"Transfer-Encoding: chunked"])
def test_bad_framing_is_400_and_closes(running, header):
    httpd, token, _ = running
    req = b"POST /answers HTTP/1.1\r\nHost: x\r\n" + header + b"\r\n\r\n5\r\nhello\r\n0\r\n\r\n"
    reply = _raw(httpd, req)  # returns only because the server closed the connection
    assert " 400 " in _status(reply)
    assert reply.lower().count(b"http/1.1 ") == 1  # the body was not parsed as a request
    assert _get(httpd, "/health", token)[0] == 200


def test_stalled_body_times_out(running, monkeypatch):
    httpd, token, _ = running
    monkeypatch.setattr(server._Handler, "timeout", 0.5)
    started = time.monotonic()
    reply = _raw(httpd, b"POST /answers HTTP/1.1\r\nHost: x\r\nContent-Length: 99999999\r\n\r\nabc")
    assert reply == b""  # connection dropped by the server...
    assert time.monotonic() - started < 3  # ...well before the client's own 5s timeout
    assert _get(httpd, "/health", token)[0] == 200


def test_handler_has_a_default_socket_timeout():
    assert server.REQUEST_TIMEOUT > 0
    assert server._Handler.timeout == server.REQUEST_TIMEOUT

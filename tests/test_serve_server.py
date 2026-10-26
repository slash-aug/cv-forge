import json
import threading
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
    assert capsys.readouterr().err.strip() == f"cv-forge server already running on port {port}"


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

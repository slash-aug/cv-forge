import json

import pytest

from cvforge import __version__
from cvforge.apply.posting import Posting
from cvforge.serve import token as token_mod
from cvforge.serve.app import VERSION, App, Request
from cvforge.track import tracker

PORT = 47321
TOKEN = "test-token"
KIT = {"schema_version": 2, "links": {"cv_pdf": "cv.pdf", "letter_pdf": "letter.pdf"}}
KIT_BYTES = (json.dumps(KIT, indent=2) + "\n").encode()


def req(method, path, query=None, headers=None, body=b""):
    base = {"host": f"127.0.0.1:{PORT}", "x-cvforge-token": TOKEN, "origin": "moz-extension://abc"}
    base.update({k.lower(): v for k, v in (headers or {}).items()})
    base = {k: v for k, v in base.items() if v is not None}
    return Request(method, path, query or {}, base, body)


def write_app(data, slug, kit=KIT_BYTES, pdfs=("cv.pdf", "letter.pdf")):
    app_dir = data / "applications" / slug
    Posting(company="Example Corp", title="Engineer", location="Remote",
            location_requirements=[], workplace="remote", salary=None, language="en",
            url=f"https://jobs.example.com/{slug}", apply_url=None, source="test",
            fetched="2026-10-22", description="A fictional role.").save(app_dir)
    if kit is not None:
        (app_dir / "kit.json").write_bytes(kit)
    for name in pdfs:
        (app_dir / name).write_bytes(b"%PDF-1.4 fake")
    return app_dir


@pytest.fixture
def data(tmp_path):
    write_app(tmp_path, "acme")
    tracker.upsert(tmp_path / "tracker.csv", {"slug": "acme", "company": "Example Corp",
                                              "role": "Engineer", "status": "drafted"})
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "master.yaml").write_text("secret: yes\n")
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / "bank.yaml").write_text(
        "- key: what notice period\n  question: What is your notice period?\n"
        "  answer: One month.\n  lang: en\n")
    return tmp_path


@pytest.fixture
def app(data):
    return App(data, TOKEN, PORT)


def body(resp):
    return json.loads(resp.body)


def test_token_created_once_with_private_mode(tmp_path):
    first = token_mod.load_or_create(tmp_path)
    second = token_mod.load_or_create(tmp_path)
    path = tmp_path / "serve" / "token"
    assert first == second and len(first) >= 32
    assert path.stat().st_mode & 0o777 == 0o600


def test_missing_or_wrong_token_is_401(app):
    for headers in ({"x-cvforge-token": None}, {"x-cvforge-token": "wrong"}):
        resp = app.handle(req("GET", "/health", headers=headers))
        assert resp.status == 401 and body(resp)["error"] == "token"


def test_bad_host_is_403(app):
    resp = app.handle(req("GET", "/health", headers={"Host": "evil.example:47321"}))
    assert resp.status == 403
    resp = app.handle(req("GET", "/health", headers={"Host": "127.0.0.1:1"}))
    assert resp.status == 403
    assert app.handle(req("GET", "/health", headers={"Host": f"localhost:{PORT}"})).status == 200


def test_web_origin_is_403(app):
    resp = app.handle(req("GET", "/health", headers={"Origin": "https://evil.example"}))
    assert resp.status == 403


def test_no_origin_is_allowed(app):
    resp = app.handle(req("GET", "/health", headers={"origin": None}))
    assert resp.status == 200 and "Access-Control-Allow-Origin" not in resp.headers


def test_preflight_needs_no_token(app):
    resp = app.handle(req("OPTIONS", "/kit/acme", headers={"x-cvforge-token": None}))
    assert resp.status == 204
    assert resp.headers["Access-Control-Allow-Origin"] == "moz-extension://abc"
    assert resp.headers["Access-Control-Allow-Headers"] == "X-CVForge-Token, Content-Type"
    assert resp.headers["Access-Control-Allow-Methods"] == "GET, POST"


def test_preflight_bad_origin_or_host_is_403(app):
    assert app.handle(req("OPTIONS", "/health", headers={"Origin": "https://evil.example"})).status == 403
    assert app.handle(req("OPTIONS", "/health", headers={"Host": "evil.example"})).status == 403


def test_health(app):
    resp = app.handle(req("GET", "/health"))
    assert resp.status == 200
    assert body(resp) == {"version": VERSION, "cvforge": __version__}
    assert resp.headers["Access-Control-Allow-Origin"] == "moz-extension://abc"
    assert resp.content_type == "application/json"


def test_error_responses_echo_origin(app):
    resp = app.handle(req("GET", "/health", headers={"x-cvforge-token": "bad"}))
    assert resp.headers["Access-Control-Allow-Origin"] == "moz-extension://abc"


def test_jobs_lists_drafted_only(app, data):
    write_app(data, "done")
    tracker.upsert(data / "tracker.csv", {"slug": "done", "company": "Other", "role": "X",
                                          "status": "applied"})
    resp = app.handle(req("GET", "/jobs"))
    assert body(resp) == [{"slug": "acme", "company": "Example Corp", "role": "Engineer",
                           "posting_url": "https://jobs.example.com/acme", "apply_url": None}]


def test_match_linkedin_refused(app):
    resp = app.handle(req("GET", "/match", {"url": "https://www.linkedin.com/jobs/view/1"}))
    assert resp.status == 403 and body(resp)["error"] == "linkedin"


@pytest.mark.parametrize("url", [None, "", "linkedin.com/jobs/view/1", "//linkedin.com/x",
                                 "ftp://jobs.example.com/acme", "https:///acme", "javascript:alert(1)"])
def test_match_bad_url_is_400(app, url):
    resp = app.handle(req("GET", "/match", {} if url is None else {"url": url}))
    assert resp.status == 400 and body(resp)["error"] == "bad-url"


def test_match_returns_slug(app):
    resp = app.handle(req("GET", "/match", {"url": "https://jobs.example.com/acme/apply"}))
    assert resp.status == 200 and body(resp) == {"slugs": ["acme"]}
    resp = app.handle(req("GET", "/match", {"url": "https://jobs.example.com/other"}))
    assert body(resp) == {"slugs": []}


def test_kit_served_verbatim(app):
    resp = app.handle(req("GET", "/kit/acme"))
    assert resp.status == 200 and resp.body == KIT_BYTES


def test_missing_kit_is_no_kit(app, data):
    write_app(data, "bare", kit=None)
    resp = app.handle(req("GET", "/kit/bare"))
    assert resp.status == 404 and body(resp)["error"] == "no-kit"


def test_pdfs_served(app):
    for name in ("cv.pdf", "letter.pdf"):
        resp = app.handle(req("GET", f"/kit/acme/{name}"))
        assert resp.status == 200 and resp.content_type == "application/pdf"
        assert resp.body.startswith(b"%PDF")


@pytest.mark.parametrize("path", ["/kit/..%2Fprofile", "/kit/ACME", "/kit/nope",
                                  "/kit/acme/../../profile/master.yaml",
                                  "/kit/..%2Fprofile/cv.pdf", "/kit/%2e%2e", "/nowhere"])
def test_bad_slug_paths_404(app, path):
    resp = app.handle(req("GET", path))
    assert resp.status == 404
    assert b"secret" not in resp.body


def test_pdf_named_outside_dir_404(app, data):
    (data / "applications" / "x.pdf").write_bytes(b"%PDF outside")
    kit = {"links": {"cv_pdf": "../x.pdf", "letter_pdf": "sub\\x.pdf"}}
    (data / "applications" / "acme" / "kit.json").write_text(json.dumps(kit))
    for name in ("cv.pdf", "letter.pdf"):
        assert app.handle(req("GET", f"/kit/acme/{name}")).status == 404


def test_pdf_link_must_end_in_pdf(app, data):
    (data / "applications" / "acme" / "kit.json").write_text(json.dumps({"links": {"cv_pdf": "posting.json"}}))
    assert app.handle(req("GET", "/kit/acme/cv.pdf")).status == 404


def test_missing_pdf_404(app, data):
    (data / "applications" / "acme" / "letter.pdf").unlink()
    assert app.handle(req("GET", "/kit/acme/letter.pdf")).status == 404
    (data / "applications" / "acme" / "kit.json").write_text(json.dumps({"links": {}}))
    assert app.handle(req("GET", "/kit/acme/cv.pdf")).status == 404


def test_bank_hit_and_miss(app):
    resp = app.handle(req("GET", "/bank", {"q": "What is your notice period?", "lang": "en"}))
    assert body(resp) == {"entry": {"question": "What is your notice period?", "answer": "One month."}}
    resp = app.handle(req("GET", "/bank", {"q": "Favourite colour?", "lang": "en"}))
    assert body(resp) == {"entry": None}
    resp = app.handle(req("GET", "/bank", {"q": "What is your notice period?", "lang": "pt"}))
    assert body(resp) == {"entry": None}


def test_unsupported_method_is_405(app):
    assert app.handle(req("DELETE", "/health")).status == 405

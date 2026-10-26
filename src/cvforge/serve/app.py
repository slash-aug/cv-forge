"""Request handling for `cvforge serve`. No sockets here, so it is unit-testable."""
from __future__ import annotations

import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cvforge import __version__
from cvforge.answers.bank import load_bank, lookup
from cvforge.profile.model import ProfileError
from cvforge.serve import matching

VERSION = "1"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EXTENSION_SCHEMES = ("chrome-extension", "moz-extension")
PDF_KEYS = {"cv.pdf": "cv_pdf", "letter.pdf": "letter_pdf"}


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]  # names lowercased
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


def _json(status: int, payload) -> Response:
    return Response(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _error(status: int, code: str, message: str) -> Response:
    return _json(status, {"error": code, "message": message})


def _absolute_http(url: str) -> bool:
    try:
        parts = urlsplit(url.strip())
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


class App:
    def __init__(self, data_dir: Path, token: str, port: int,
                 today: Callable[[], date] = date.today, master_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.token = token
        self.port = port
        self.today = today
        self.master_path = master_path
        self.routes: list[tuple[str, re.Pattern, Callable[..., Response]]] = [
            ("GET", re.compile(r"/health"), self._health),
            ("GET", re.compile(r"/jobs"), self._jobs),
            ("GET", re.compile(r"/match"), self._match),
            ("GET", re.compile(r"/kit/([^/]+)"), self._kit),
            ("GET", re.compile(r"/kit/([^/]+)/(cv\.pdf|letter\.pdf)"), self._pdf),
            ("GET", re.compile(r"/bank"), self._bank),
        ]

    # guards and dispatch

    def handle(self, req: Request) -> Response:
        host = req.headers.get("host", "")
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return _error(403, "host", "Host not allowed.")
        origin = req.headers.get("origin")
        cors: dict[str, str] = {}
        if origin is not None:
            if urlsplit(origin).scheme not in EXTENSION_SCHEMES:
                return _error(403, "origin", "Origin not allowed.")
            cors = {"Access-Control-Allow-Origin": origin}
        if req.method == "OPTIONS" and origin is not None:
            return Response(204, b"", headers={
                **cors,
                "Access-Control-Allow-Headers": "X-CVForge-Token, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST"})
        given = req.headers.get("x-cvforge-token", "")
        if not hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8")):
            resp = _error(401, "token", "Missing or wrong pairing token.")
        else:
            resp = self._dispatch(req)
        resp.headers.update(cors)
        return resp

    def _dispatch(self, req: Request) -> Response:
        path = unquote(req.path)
        known = False
        for method, pattern, handler in self.routes:
            found = pattern.fullmatch(path)
            if not found:
                continue
            known = True
            if method == req.method:
                return handler(req, *found.groups())
        if known:
            return _error(405, "method", "Method not allowed.")
        return _error(404, "not-found", "No such endpoint.")

    # helpers

    def _app_dir(self, slug: str) -> Path | None:
        if not SLUG.fullmatch(slug):
            return None
        app_dir = self.data_dir / "applications" / slug
        return app_dir if app_dir.is_dir() else None

    def _kit_links(self, app_dir: Path) -> dict:
        try:
            links = json.loads((app_dir / "kit.json").read_bytes()).get("links")
        except (OSError, ValueError, AttributeError):
            return {}
        return links if isinstance(links, dict) else {}

    # handlers

    def _health(self, req: Request) -> Response:
        return _json(200, {"version": VERSION, "cvforge": __version__})

    def _jobs(self, req: Request) -> Response:
        return _json(200, [{"slug": j.slug, "company": j.company, "role": j.role,
                            "posting_url": j.posting_url, "apply_url": j.apply_url}
                           for j in matching.open_jobs(self.data_dir)])

    def _match(self, req: Request) -> Response:
        url = req.query.get("url", "")
        if not _absolute_http(url):
            return _error(400, "bad-url", "url must be an absolute http(s) URL.")
        try:
            slugs = matching.match(matching.open_jobs(self.data_dir), url,
                                   req.query.get("site") or None, req.query.get("job_id") or None)
        except matching.LinkedInRefused:
            return _error(403, "linkedin", "LinkedIn pages are never matched or filled.")
        return _json(200, {"slugs": slugs})

    def _kit(self, req: Request, slug: str) -> Response:
        app_dir = self._app_dir(slug)
        if app_dir is None:
            return _error(404, "no-app", "No such application.")
        kit = app_dir / "kit.json"
        if not kit.is_file():
            return _error(404, "no-kit", f"No kit yet. Run cvforge kit {slug}.")
        return Response(200, kit.read_bytes())

    def _pdf(self, req: Request, slug: str, name: str) -> Response:
        app_dir = self._app_dir(slug)
        if app_dir is None:
            return _error(404, "no-app", "No such application.")
        link = self._kit_links(app_dir).get(PDF_KEYS[name])
        if (not isinstance(link, str) or not link.endswith(".pdf")
                or "/" in link or "\\" in link or ".." in link):
            return _error(404, "no-pdf", "No such PDF.")
        pdf = app_dir / link
        if not pdf.is_file():
            return _error(404, "no-pdf", "No such PDF.")
        return Response(200, pdf.read_bytes(), content_type="application/pdf")

    def _bank(self, req: Request) -> Response:
        try:
            bank = load_bank(self.data_dir / "answers" / "bank.yaml")
        except ProfileError as exc:
            return _error(500, "bank", str(exc))
        hit = lookup(bank, req.query.get("q", ""), req.query.get("lang", "en"))
        return _json(200, {"entry": {"question": hit.get("question", ""), "answer": hit["answer"]}
                           if hit else None})

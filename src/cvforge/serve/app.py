"""Request handling for `cvforge serve`. No sockets here, so it is unit-testable."""
from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from cvforge import __version__
from cvforge.answers.bank import load_bank, lookup, save_answers
from cvforge.answers.grounding import DataError, answer_figures
from cvforge.profile.model import ProfileError, load_master
from cvforge.serve import matching
from cvforge.tailor.audit import audit_answer
from cvforge.track import tracker

VERSION = "1"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
EXTENSION_SCHEMES = ("chrome-extension", "moz-extension")
MAX_BODY = 64 * 1024
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
            ("POST", re.compile(r"/answers/([^/]+)"), self._save_answer),
            ("POST", re.compile(r"/applied/([^/]+)"), self._mark_applied),
        ]

    # guards and dispatch

    def handle(self, req: Request) -> Response:
        host = req.headers.get("host", "")
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return _error(403, "host", "Host not allowed.")
        origin = req.headers.get("origin")
        cors: dict[str, str] = {}
        if origin is not None:
            try:
                scheme = urlsplit(origin).scheme
            except ValueError:
                scheme = ""
            if scheme not in EXTENSION_SCHEMES:
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
        except ProfileError:
            return _error(500, "bank", "Answer bank is unreadable. Run cvforge answers to check it.")
        hit = lookup(bank, req.query.get("q", ""), req.query.get("lang", "en"))
        return _json(200, {"entry": {"question": hit.get("question", ""), "answer": hit["answer"]}
                           if hit else None})

    def _lang(self, app_dir: Path) -> str:
        for name, read in (("kit.json", json.loads), ("tailored.yaml", yaml.safe_load)):
            try:
                lang = read((app_dir / name).read_text(encoding="utf-8")).get("lang")
            except (OSError, ValueError, AttributeError, yaml.YAMLError):
                continue
            if isinstance(lang, str) and lang:
                return lang
            if name == "kit.json" and (app_dir / name).exists():
                break
        return "en"

    def _save_answer(self, req: Request, slug: str) -> Response:
        app_dir = self._app_dir(slug)
        if app_dir is None:
            return _error(404, "no-app", "No such application.")
        if len(req.body) > MAX_BODY:
            return _error(413, "too-large", "Body is larger than 64 KiB.")
        try:
            payload = json.loads(req.body)
        except ValueError:
            return _error(400, "bad-body", "Body must be JSON.")
        question = payload.get("question") if isinstance(payload, dict) else None
        answer = payload.get("answer") if isinstance(payload, dict) else None
        if (not isinstance(question, str) or not isinstance(answer, str)
                or not question.strip() or not answer.strip()):
            return _error(400, "bad-body", "question and answer must be non-empty strings.")
        lang = self._lang(app_dir)
        today = self.today()
        try:
            master = load_master(self.master_path or self.data_dir / "profile" / "master.yaml")
        except ProfileError:
            return _error(500, "master", "Master profile is unreadable. Run cvforge validate.")
        try:
            allowed = answer_figures(master, lang, app_dir, today)
        except DataError:
            return _error(500, "salary", "salary.json is damaged. Rerun cvforge salary.")
        findings = audit_answer(question, answer, master, extra_allowed=allowed)
        if findings:
            return _json(422, {"error": "audit", "findings": [
                {"kind": f.kind, "ref": f.ref, "message": f.message} for f in findings]})
        sent_path = app_dir / "answers_sent.yaml"
        try:
            sent = yaml.safe_load(sent_path.read_text(encoding="utf-8")) if sent_path.exists() else []
            if sent is None:
                sent = []
            if not isinstance(sent, list):
                raise TypeError
            save_answers(self.data_dir / "answers" / "bank.yaml",
                         [{"question": question, "answer": answer, "refs": []}], lang, today)
            sent.append({"date": today.isoformat(), "question": question, "answer": answer})
            tmp = sent_path.with_name(sent_path.name + ".tmp")
            tmp.write_text(yaml.safe_dump(sent, sort_keys=False, allow_unicode=True,
                                          default_flow_style=False), encoding="utf-8")
            os.replace(tmp, sent_path)
        except (OSError, TypeError, ValueError, yaml.YAMLError, ProfileError):
            return _error(500, "save", "Could not save the answer. Run cvforge answers to check the bank.")
        return _json(200, {"saved": True})

    def _mark_applied(self, req: Request, slug: str) -> Response:
        if not SLUG.fullmatch(slug):
            return _error(404, "no-row", "No such application.")
        try:
            tracker.set_status(self.data_dir / "tracker.csv", slug, "applied", self.today())
        except KeyError:
            return _error(404, "no-row", "No such application.")
        except (OSError, ValueError):
            return _error(500, "tracker", "Tracker is unreadable. Run cvforge due to check it.")
        return _json(200, {"status": "applied"})

"""Match a form page to an open (drafted) application."""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from cvforge.apply.http import host_of, is_linkedin, on_domain
from cvforge.apply.posting import Posting, canonical_url
from cvforge.track import tracker

GREENHOUSE_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io")


class LinkedInRefused(Exception):
    """LinkedIn pages are never matched or filled."""


@dataclass(frozen=True)
class OpenJob:
    slug: str
    company: str
    role: str
    posting_url: str
    apply_url: str | None


def _digits(value: str | None) -> str | None:
    return value if value and value.isascii() and value.isdigit() else None


def _gupy_code(code: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
        data = json.loads(raw)
    except (binascii.Error, ValueError):
        return None
    job_id = data.get("jobId") if isinstance(data, dict) else None
    return _digits(str(job_id)) if isinstance(job_id, int) and not isinstance(job_id, bool) else None


def site_job_id(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url.strip())
    host, path = host_of(url), parts.path
    query = parse_qs(parts.query)

    def first(key: str) -> str | None:
        return query[key][0] if query.get(key) else None

    if host in GREENHOUSE_HOSTS:
        found = re.fullmatch(r"/[^/]+/jobs/([^/]+)/?", path)
        if found and _digits(found.group(1)):
            return "greenhouse", found.group(1)
        if path.rstrip("/") == "/embed/job_app" and _digits(first("token")):
            return "greenhouse", first("token")
    if _digits(first("gh_jid")):
        return "greenhouse", first("gh_jid")
    if on_domain(host, "gupy.io"):
        found = re.search(r"/job/([A-Za-z0-9_=-]+)", path)
        if found and (job_id := _gupy_code(found.group(1))):
            return "gupy", job_id
        found = re.search(r"/jobs/(\d+)(?:/|$)", path)
        if found and _digits(found.group(1)):
            return "gupy", found.group(1)
    return None


def url_key(url: str) -> tuple[str, str]:
    parts = urlsplit(canonical_url(url))
    host = (parts.hostname or "").lower().rstrip(".")
    host = host.removeprefix("www.")
    return host, parts.path.rstrip("/")


def open_jobs(data_dir: Path) -> list[OpenJob]:
    jobs = []
    for row in tracker.load(data_dir / "tracker.csv"):
        if row["status"] != "drafted" or not row["slug"]:
            continue
        app_dir = data_dir / "applications" / row["slug"]
        if not (app_dir / "posting.json").exists():
            continue
        posting = Posting.load(app_dir)
        jobs.append(OpenJob(slug=row["slug"], company=row["company"] or posting.company,
                            role=row["role"] or posting.title, posting_url=posting.url,
                            apply_url=posting.apply_url or None))
    return jobs


def _urls(job: OpenJob) -> list[str]:
    return [u for u in (job.posting_url, job.apply_url) if u]


def match(jobs: list[OpenJob], url: str, site: str | None = None,
          job_id: str | None = None) -> list[str]:
    if is_linkedin(url):
        raise LinkedInRefused(url)
    if site and job_id:
        wanted = (site, job_id)
        slugs = [j.slug for j in jobs if any(site_job_id(u) == wanted for u in _urls(j))]
        if slugs:
            return slugs
    host, path = url_key(url)
    slugs = []
    for j in jobs:
        for u in _urls(j):
            job_host, job_path = url_key(u)
            if job_host == host and job_path and (path == job_path or path.startswith(job_path + "/")):
                slugs.append(j.slug)
                break
    return slugs

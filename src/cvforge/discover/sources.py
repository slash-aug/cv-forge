"""Public job-board feeds (Greenhouse, Ashby, Lever, Workable) as lists of Role records."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cvforge.apply import http
from cvforge.apply.companies import board_slug
from cvforge.apply.intake import (
    Get,
    IntakeError,
    _ashby_job,
    _build,
    _greenhouse_job,
    _json,
    _lever_job,
    _number,
)
from cvforge.apply.posting import Posting, canonical_url

PERIODS = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour"}
SKIPPABLE = (KeyError, TypeError, ValueError, AttributeError, IntakeError)


@dataclass
class Role:
    source: str
    board: str
    job_id: str
    company: str
    title: str
    location: str
    workplace: str | None
    url: str
    description: str
    salary: dict | None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.board}:{self.job_id}"


class SourceError(Exception):
    """A board could not be read this run."""


def board_url(ats: str, slug: str) -> str:
    return {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
        "workable": f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    }[ats]


def _role(post: Posting, *, ats: str, slug: str, job_id, company: str, url: str, location: str | None = None,
          salary: dict | None = None) -> Role:
    return Role(source=ats, board=slug, job_id=str(job_id), company=company, title=post.title,
                location=post.location if location is None else location, workplace=post.workplace,
                url=url, description=post.description, salary=salary)


def _title(job: dict) -> str:
    title = job["title"] if "title" in job else job["text"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("no title")
    return title


def _greenhouse(job: dict, slug: str, name: str, today: date) -> Role:
    job_id, _title_ = job["id"], _title(job)
    url = canonical_url(job["absolute_url"])
    post = _greenhouse_job({**job, "company_name": name, "title": _title_}, org=slug, url=url, today=today)
    return _role(post, ats="greenhouse", slug=slug, job_id=job_id, company=name, url=url)


def _ashby_salary(job: dict) -> dict | None:
    components = (job.get("compensation") or {}).get("summaryComponents") or []
    item = next((c for c in components if isinstance(c, dict) and c.get("compensationType") == "Salary"), None)
    if item is None:
        return None
    period = PERIODS.get(str(item.get("interval") or "").strip().upper())
    low, high = _number(item.get("minValue")), _number(item.get("maxValue"))
    if period is None or (low is None and high is None):
        return None
    return {"currency": item.get("currencyCode"), "min": low, "max": high, "period": period}


def _ashby(job: dict, slug: str, name: str, today: date) -> Role:
    job_id, _ = job["id"], _title(job)
    url = canonical_url(job["jobUrl"])
    post = _ashby_job(job, org=slug, url=url, today=today)
    places = [x for x in [job.get("location"), *(s.get("location") for s in job.get("secondaryLocations") or [])]
              if x]
    return _role(post, ats="ashby", slug=slug, job_id=job_id, company=name, url=url,
                 location="; ".join(places), salary=_ashby_salary(job))


def _lever(job: dict, slug: str, name: str, today: date) -> Role:
    job_id, _ = job["id"], _title(job)
    url = canonical_url(job["hostedUrl"])
    post = _lever_job(job, org=slug, url=url, today=today)
    salary = post.salary if post.salary and post.salary.get("period") else None
    return _role(post, ats="lever", slug=slug, job_id=job_id, company=name, url=url, salary=salary)


def _workable(job: dict, slug: str, name: str, today: date) -> Role:
    shortcode, title = job["shortcode"], _title(job)
    url = canonical_url(job.get("url") or f"https://apply.workable.com/{slug}/j/{shortcode}/")
    location = ", ".join(x for x in (job.get("city"), job.get("country")) if x)
    post = _build(company=name, title=title, location=location, workplace="remote" if job.get("telecommuting") else None,
                  url=url, source="workable", today=today, markup=job.get("description") or "")
    return _role(post, ats="workable", slug=slug, job_id=shortcode, company=name, url=url)


MAPPERS = {"greenhouse": _greenhouse, "ashby": _ashby, "lever": _lever, "workable": _workable}


def _jobs(ats: str, data) -> list:
    if ats == "lever":
        jobs = data
    elif isinstance(data, dict):
        jobs = data.get("jobs")
    else:
        jobs = None
    if not isinstance(jobs, list):
        raise SourceError(f"unexpected {ats} response shape")
    return jobs


def fetch_board(entry: dict, *, get: Get, today: date) -> list[Role]:
    ats = entry.get("ats")
    slug = board_slug(entry)
    if ats not in MAPPERS or not slug:
        raise SourceError(f"{entry.get('name', '?')}: no feed board (ats {ats!r}, slug {slug!r})")
    try:
        data = _json(get(board_url(ats, slug)))
    except (http.FetchError, IntakeError) as exc:
        raise SourceError(f"{entry.get('name', slug)}: {exc}") from exc
    roles = []
    for job in _jobs(ats, data):
        try:
            role = MAPPERS[ats](job, slug, entry["name"], today)
        except SKIPPABLE:
            continue
        if http.is_linkedin(role.url):
            continue
        roles.append(role)
    return roles

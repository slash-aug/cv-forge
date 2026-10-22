"""Turn a job link or pasted text into a Posting."""
from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from datetime import date
from urllib.parse import quote, urlsplit

from cvforge.apply import http
from cvforge.apply.posting import Posting, canonical_url, guess_language
from cvforge.apply.posting_guard import guard

Get = Callable[..., str]
LD_JSON = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
HREF = re.compile(r"href\s*=\s*[\"'](https?://[^\"']+)[\"']", re.IGNORECASE)
NO_POSTING = "no readable posting; paste the text instead"
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


class IntakeError(Exception):
    """The posting could not be read."""


def resolve_shortlink(url: str, get: Get) -> str:
    """For lnkd.in, the first link in the interstitial that is not LinkedIn's; else the url unchanged."""
    if (urlsplit(url).hostname or "").lower() not in ("lnkd.in", "www.lnkd.in"):
        return url
    for href in HREF.findall(get(url)):
        href = html.unescape(href)
        host = (urlsplit(href).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in ("linkedin.com", "licdn.com")):
            return href
    raise IntakeError("short link has no target; open it and paste the real link or the text")


def _json(text: str):
    try:
        return json.loads(text, strict=False)
    except ValueError as exc:
        raise IntakeError(f"unreadable response: {exc}") from exc


def _plain_html(markup: str) -> str:
    """Posting HTML, which APIs often ship entity-escaped, as unescaped markup."""
    if "<" not in markup and "&lt;" in markup:
        markup = html.unescape(markup)
    return markup


def _build(*, company: str, title: str, location: str = "", requirements: list[str] | None = None,
           workplace: str | None = None, salary: dict | None = None, url: str, apply_url: str | None = None,
           source: str, today: date, markup: str = "", text: str | None = None) -> Posting:
    if text is None:
        clean, findings = guard(_plain_html(markup), "html")
    else:
        clean, findings = guard(text, "text")
    return Posting(
        company=company.strip(), title=title.strip(), location=location, location_requirements=requirements or [],
        workplace=workplace, salary=salary, language=guess_language(clean), url=url, apply_url=apply_url,
        source=source, fetched=today.isoformat(), description=clean, guard=findings)


def _number(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return int(num) if num.is_integer() else num


def posting_from_text(text: str, *, company: str, role: str, url: str, today: date) -> Posting:
    return _build(company=company, title=role, url=url, source="paste", today=today, text=text)


def _ashby(org: str, job_id: str, url: str, get: Get, today: date) -> Posting:
    board = _json(get(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"))
    job = next((j for j in board.get("jobs", []) if j.get("id") == job_id), None)
    if job is None:
        raise IntakeError(f"job {job_id} not found on the {org} board; it may be closed")
    location = job.get("location") or ""
    workplace = WORKPLACE.get(str(job.get("workplaceType") or "").lower().replace(" ", ""))
    if workplace is None and job.get("isRemote"):
        workplace = "remote"
    requirements = []
    if job.get("isRemote"):
        requirements = [x for x in [location, *(s.get("location") for s in job.get("secondaryLocations") or [])] if x]
    summary = (job.get("compensation") or {}).get("compensationTierSummary")
    markup = job.get("descriptionHtml") or html.escape(job.get("descriptionPlain") or "")
    return _build(company=org, title=job.get("title", ""), location=location, requirements=requirements,
                  workplace=workplace, salary={"summary": summary} if summary else None, url=url,
                  apply_url=job.get("applyUrl"), source="ashby", today=today, markup=markup)


def _greenhouse(org: str, job_id: str, url: str, get: Get, today: date) -> Posting:
    job = _json(get(f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{job_id}"))
    return _build(company=job.get("company_name") or org, title=job.get("title", ""),
                  location=(job.get("location") or {}).get("name", ""), url=url,
                  apply_url=job.get("absolute_url"), source="greenhouse", today=today,
                  markup=_plain_html(job.get("content") or ""))


def _lever(org: str, job_id: str, url: str, get: Get, today: date) -> Posting:
    job = _json(get(f"https://api.lever.co/v0/postings/{org}/{job_id}"))
    parts = [job.get("description") or ""]
    for block in job.get("lists") or []:
        parts.append(f"<h3>{block.get('text', '')}</h3><ul>{block.get('content', '')}</ul>")
    parts.append(job.get("additional") or "")
    pay = job.get("salaryRange")
    salary = None
    if pay and (pay.get("min") or pay.get("max")):
        period = {"per-year-salary": "year", "per-month-salary": "month"}.get(pay.get("interval", ""), "")
        salary = {"currency": pay.get("currency"), "min": _number(pay.get("min")),
                  "max": _number(pay.get("max")), "period": period}
    return _build(company=org, title=job.get("text", ""), location=(job.get("categories") or {}).get("location", ""),
                  workplace=WORKPLACE.get(str(job.get("workplaceType") or "").lower()), salary=salary, url=url,
                  apply_url=job.get("applyUrl"), source="lever", today=today, markup="".join(parts))


def _find_jobposting(node):
    if isinstance(node, list):
        for item in node:
            found = _find_jobposting(item)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return node
        return _find_jobposting(node.get("@graph"))
    return None


def _names(value) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [(i.get("name") if isinstance(i, dict) else str(i)) for i in items if i]


def _place(loc: dict) -> str:
    address = loc.get("address") or {}
    if isinstance(address, str):
        return address
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    return ", ".join(x for x in (address.get("addressLocality"), country) if x)


def _apply_url(job: dict) -> str | None:
    action = job.get("potentialAction")
    if isinstance(action, list):
        action = action[0] if action else None
    if isinstance(action, dict):
        target = action.get("target")
        if isinstance(target, dict):
            target = target.get("urlTemplate")
        if target:
            return target
    return job.get("applyUrl") or None


def _jsonld_salary(base) -> dict | None:
    if not isinstance(base, dict):
        return None
    value = base.get("value")
    if not isinstance(value, dict):
        value = {"value": value}
    low = _number(value.get("minValue", value.get("value")))
    high = _number(value.get("maxValue", value.get("value")))
    if low is None and high is None:
        return None
    return {"currency": base.get("currency"), "min": low, "max": high,
            "period": str(value.get("unitText") or "").lower()}


def _jsonld(url: str, get: Get, today: date) -> Posting:
    page = get(url)
    job = None
    for block in LD_JSON.findall(page):
        try:
            job = _find_jobposting(json.loads(block.strip(), strict=False))
        except ValueError:
            continue
        if job:
            break
    if job is None:
        raise IntakeError(NO_POSTING)
    org = job.get("hiringOrganization")
    company = (org.get("name") if isinstance(org, dict) else org) or ""
    locations = job.get("jobLocation") or []
    locations = locations if isinstance(locations, list) else [locations]
    location = "; ".join(x for x in (_place(loc) for loc in locations if isinstance(loc, dict)) if x)
    requirements = _names(job.get("applicantLocationRequirements"))
    remote = str(job.get("jobLocationType") or "").upper() == "TELECOMMUTE"
    workplace = "remote" if remote else ("onsite" if location else None)
    if remote and not location:
        location = "Remote"
    return _build(company=company, title=job.get("title") or job.get("name") or "", location=location,
                  requirements=requirements, workplace=workplace, salary=_jsonld_salary(job.get("baseSalary")),
                  url=url, apply_url=_apply_url(job), source="jsonld", today=today,
                  markup=job.get("description") or "")


def fetch_posting(url: str, *, get: Get = http.get, today: date) -> Posting:
    url = canonical_url(resolve_shortlink(url, get))
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path
    seg = [quote(s, safe="-_.~") for s in path.split("/") if s]
    if host == "jobs.ashbyhq.com" and len(seg) >= 2:
        return _ashby(seg[0], seg[1], url, get, today)
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and len(seg) >= 3 and seg[1] == "jobs":
        return _greenhouse(seg[0], seg[2], url, get, today)
    if host == "jobs.lever.co" and len(seg) >= 2:
        return _lever(seg[0], seg[1], url, get, today)
    return _jsonld(url, get, today)

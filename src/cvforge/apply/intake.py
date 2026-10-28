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
NEXT_DATA = re.compile(
    r"<script\b[^>]*id\s*=\s*[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script\s*>", re.IGNORECASE | re.DOTALL)
GUPY_CONTRACT = {"vacancy_type_effective": "CLT", "vacancy_legal_entity": "PJ",
                 "vacancy_type_internship": "internship", "vacancy_type_trainee": "trainee",
                 "vacancy_type_temporary": "temporary", "vacancy_type_freelancer": "freelancer",
                 "vacancy_type_autonomous": "freelancer"}
FLIGHT_PUSH = re.compile(r"self\.__next_f\.push\(\[1,(\"(?:[^\"\\]|\\.)*\")\]\)", re.DOTALL)
GH_EMBEDDED_JOB = re.compile(r'"job":(?=\{"absolute_url":)')
HREF = re.compile(r"href\s*=\s*[\"'](https?://[^\"']+)[\"']", re.IGNORECASE)
NO_POSTING = "no readable posting; paste the text instead"
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


LINKEDIN_REFUSED = ("LinkedIn pages are never fetched; paste the posting text with "
                    "`intake - --company --role`, or use the employer's own link")


class IntakeError(Exception):
    """The posting could not be read."""


_on = http.on_domain
is_linkedin = http.is_linkedin


def refuse_linkedin(url: str) -> None:
    """Refuse LinkedIn links (with or without a scheme) and anything that is not http(s)."""
    url = url.strip()
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        if "://" not in url and is_linkedin("https://" + url):
            raise IntakeError(LINKEDIN_REFUSED)
        raise IntakeError(f"not a web link: {url!r}; include https:// (or paste the text with `intake -`)")
    if is_linkedin(url):
        raise IntakeError(LINKEDIN_REFUSED)


def resolve_shortlink(url: str, get: Get) -> str:
    """For lnkd.in, the first link in the interstitial that is not LinkedIn's; else the url unchanged."""
    refuse_linkedin(url)
    if (urlsplit(url).hostname or "").lower() not in ("lnkd.in", "www.lnkd.in"):
        return url
    to_linkedin_job = False
    for href in HREF.findall(get(url)):
        href = html.unescape(href)
        parts = urlsplit(href)
        host = http.host_of(href)
        if not any(_on(host, d) for d in ("linkedin.com", "licdn.com")):
            return href
        to_linkedin_job = to_linkedin_job or (_on(host, "linkedin.com") and "/jobs/" in parts.path)
    if to_linkedin_job:
        raise IntakeError(LINKEDIN_REFUSED)
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
    return _ashby_job(job, org=org, url=url, today=today)


def _ashby_job(job: dict, *, org: str, url: str, today: date) -> Posting:
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


def _greenhouse_job(job: dict, *, org: str, url: str, today: date) -> Posting:
    """A Greenhouse job record, from the board API or embedded in a careers page."""
    markup = _plain_html(job.get("content") or "")
    for field in job.get("metadata") or []:
        if isinstance(field, dict) and field.get("name") == "Employment Type" and isinstance(field.get("value"), str):
            markup += f"<p>Employment type: {html.escape(field['value'])} (Greenhouse job field)</p>"
    return _build(company=job.get("company_name") or org, title=job.get("title", ""),
                  location=(job.get("location") or {}).get("name", ""), url=url,
                  apply_url=job.get("absolute_url"), source="greenhouse", today=today, markup=markup)


def _greenhouse(org: str, job_id: str, url: str, get: Get, today: date) -> Posting:
    job = _json(get(f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs/{job_id}"))
    return _greenhouse_job(job, org=org, url=url, today=today)


def _flight_data(page: str) -> str:
    """The Next.js App Router stream (self.__next_f pushes) of a page, joined into one string."""
    parts = []
    for chunk in FLIGHT_PUSH.findall(page):
        try:
            parts.append(json.loads(chunk))
        except ValueError:
            continue
    return "".join(parts)


def _flight_text(flight: str, ref: str) -> str | None:
    """A text row ("<id>:T<hex byte length>,<text>") that a "$<id>" value points to."""
    match = re.search(r"(?:^|\n)" + re.escape(ref) + r":T([0-9a-fA-F]+),", flight)
    if match is None:
        return None
    raw = flight.encode("utf-8")
    start = len(flight[:match.end()].encode("utf-8"))
    return raw[start:start + int(match.group(1), 16)].decode("utf-8", errors="replace")


def _greenhouse_embedded(url: str, page: str, today: date) -> Posting | None:
    """A Greenhouse job that a custom careers site (Next.js) ships in its page stream, or None."""
    flight = _flight_data(page)
    decoder = json.JSONDecoder(strict=False)
    for match in GH_EMBEDDED_JOB.finditer(flight):
        try:
            job, _ = decoder.raw_decode(flight, match.end())
        except ValueError:
            continue
        if not isinstance(job, dict) or not job.get("title") or not job.get("content"):
            continue
        content = job["content"]
        if isinstance(content, str) and re.fullmatch(r"\$[0-9a-fA-F]+", content):
            job = {**job, "content": _flight_text(flight, content[1:]) or ""}
        return _greenhouse_job(job, org="", url=url, today=today)
    return None


def _lever(org: str, job_id: str, url: str, get: Get, today: date) -> Posting:
    job = _json(get(f"https://api.lever.co/v0/postings/{org}/{job_id}"))
    return _lever_job(job, org=org, url=url, today=today)


def _lever_job(job: dict, *, org: str, url: str, today: date) -> Posting:
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
    """Names from a schema.org value or list; entries with no name (None, "", {}) are dropped."""
    items = value if isinstance(value, list) else [value]
    names = [(i.get("name") if isinstance(i, dict) else i) for i in items]
    return [str(n).strip() for n in names if n is not None and str(n).strip()]


def _place(loc: dict) -> str:
    address = loc.get("address") or {}
    if isinstance(address, list):  # some sites send a list; the first postal address counts
        address = next((a for a in address if isinstance(a, dict)), {})
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


def _ld_block(block: str):
    """One JSON-LD block; some sites (Gupy) ship it entity-escaped."""
    block = block.strip()
    try:
        return json.loads(block, strict=False)
    except ValueError:
        return json.loads(html.unescape(block), strict=False)


def _jsonld(url: str, page: str, today: date) -> Posting:
    job = None
    for block in LD_JSON.findall(page):
        try:
            job = _find_jobposting(_ld_block(block))
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


def _gupy(url: str, get: Get, today: date) -> Posting:
    """Gupy pages carry the job in Next.js page data; without it, fall back to JSON-LD."""
    page = get(url)
    match = NEXT_DATA.search(page)
    try:
        job = json.loads(match.group(1), strict=False)["props"]["pageProps"]["job"] if match else None
    except (ValueError, KeyError, TypeError):
        job = None
    if not isinstance(job, dict) or not job.get("name"):
        return _jsonld(url, page, today)
    country = str(job.get("addressCountry") or "").strip()
    location = ", ".join(x for x in (job.get("addressCity"), job.get("addressState"), country) if x)
    workplace = WORKPLACE.get(str(job.get("workplaceType") or "").lower())
    sections = [job.get(k) or "" for k in ("description", "responsibilities", "prerequisites", "relevantExperiences")]
    contract = GUPY_CONTRACT.get(str(job.get("jobType") or ""))
    if contract:
        sections.append(f"<p>Contract: {contract} (Gupy job type)</p>")
    company = (job.get("careerPage") or {}).get("name") or ""
    return _build(company=company, title=job["name"], location=location,
                  requirements=[country] if workplace == "remote" and country else [], workplace=workplace,
                  url=url, apply_url=url, source="gupy", today=today, markup="".join(sections))


def fetch_posting(url: str, *, get: Get = http.get, today: date) -> Posting:
    url = canonical_url(resolve_shortlink(url, get))
    refuse_linkedin(url)
    parts = urlsplit(url)
    host, path = (parts.hostname or "").lower(), parts.path
    seg = [quote(s, safe="-_.~") for s in path.split("/") if s]
    if host == "jobs.ashbyhq.com" and len(seg) >= 2:
        return _ashby(seg[0], seg[1], url, get, today)
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io") and len(seg) >= 3 and seg[1] == "jobs":
        return _greenhouse(seg[0], seg[2], url, get, today)
    if host == "jobs.lever.co" and len(seg) >= 2:
        return _lever(seg[0], seg[1], url, get, today)
    if http.on_domain(host, "gupy.io"):
        return _gupy(url, get, today)
    page = get(url)
    try:
        return _jsonld(url, page, today)
    except IntakeError:
        embedded = _greenhouse_embedded(url, page, today)
        if embedded is None:
            raise
        return embedded

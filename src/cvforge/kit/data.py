"""Build the kit data: form fields, jobs with descriptions cut to portal limits, salary, answers."""
from __future__ import annotations

import re

from cvforge.answers.facts import visa_text
from cvforge.profile.model import index, localized
from cvforge.render.cv import build_cv_view
from cvforge.text import split_name

SCHEMA_VERSION = 1
LIMITS = (200, 500, 1000, 2000)
UNCONFIRMED = "unconfirmed: run cvforge salary {slug} --confirm"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_TRAILING = " ,;:-"


def _fit_words(text: str, limit: int) -> str:
    out = ""
    for word in text.split():
        candidate = f"{out} {word}" if out else word
        if len(candidate) > limit:
            break
        out = candidate
    return out.rstrip(_TRAILING) if out.rstrip(_TRAILING) else ""


def _fit_sentences(line: str, limit: int) -> str:
    out = ""
    for sentence in _SENTENCE_END.split(line):
        candidate = f"{out} {sentence}" if out else sentence
        if len(candidate) > limit:
            break
        out = candidate
    return out or _fit_words(line, limit)


def cut(text: str, limit: int) -> str:
    """At most `limit` characters: whole bullet lines, else whole sentences, else whole words."""
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for line in text.split("\n"):
        candidate = "\n".join([*kept, line])
        if len(candidate) > limit:
            break
        kept.append(line)
    if kept:
        return "\n".join(kept)
    return _fit_sentences(text.split("\n", 1)[0], limit)


def _field(key: str, label: str, value, group: str) -> dict | None:
    value = "" if value is None else str(value).strip()
    return {"key": key, "label": label, "value": value, "group": group} if value else None


def _profile_url(basics: dict, *networks: str) -> str:
    for profile in basics.get("profiles", []):
        if profile.get("network", "").casefold() in networks:
            return profile["url"]
    return ""


def _fields(master: dict) -> list[dict]:
    basics = master["basics"]
    location = basics.get("location") or {}
    prefs = master.get("x-preferences") or {}
    first, last = split_name(basics["name"])
    visa = visa_text(prefs.get("visa")) or None
    relocation = prefs.get("relocation")
    rows = [
        _field("basics.name", "Full name", basics["name"], "personal"),
        _field("basics.first_name", "First name", first, "personal"),
        _field("basics.last_name", "Last name", last, "personal"),
        _field("basics.email", "Email", basics.get("email"), "personal"),
        _field("basics.phone", "Phone", basics.get("phone"), "personal"),
        _field("basics.city", "City", location.get("city"), "personal"),
        _field("basics.region", "Region", location.get("region"), "personal"),
        _field("basics.country", "Country", location.get("countryCode"), "personal"),
        _field("basics.linkedin", "LinkedIn", _profile_url(basics, "linkedin"), "links"),
        _field("basics.github", "GitHub", _profile_url(basics, "github"), "links"),
        _field("basics.portfolio", "Portfolio",
               _profile_url(basics, "portfolio", "website", "web"), "links"),
        _field("prefs.visa", "Visa / work authorisation", visa, "preferences"),
        _field("prefs.notice", "Notice period", prefs.get("noticePeriod"), "preferences"),
        _field("prefs.relocation", "Open to relocation",
               None if relocation is None else ("yes" if relocation else "no"), "preferences"),
    ]
    return [r for r in rows if r]


def _work(master: dict, tailored: dict) -> list[dict]:
    """One entry per selected position, in CV order (employers as selected, newest role first)."""
    ids = index(master)
    lang = tailored["lang"]
    jobs = []
    for entry in tailored.get("experience", []):
        employer = ids[entry["ref"]][1]
        company = localized(employer["name"], lang, item_id=employer["id"])
        rows = sorted(((ids[p["ref"]][1], p) for p in entry["positions"]),
                      key=lambda pair: pair[0]["startDate"], reverse=True)
        for position, ref in rows:
            text = "\n".join(f"- {b['text']}" for b in ref["bullets"])
            jobs.append({
                "key": f"work.{len(jobs)}",
                "title": localized(position["title"], lang, item_id=position["id"]),
                "company": company,
                "start": position["startDate"],
                "end": position.get("endDate"),
                "description": {str(limit): cut(text, limit) for limit in LIMITS},
            })
    return jobs


def _salary(salary: dict | None, slug: str) -> dict | None:
    if salary is None:
        return None
    if not salary.get("confirmed"):
        return {"confirmed": False, "text": UNCONFIRMED.format(slug=slug), "sources": []}
    text = (f"{salary['amount']:,.0f} {salary['currency']}/{salary['period']}"
            f" (BRL {salary['brl_month']:,.0f}/month, EUR {salary['eur_year']:,.0f}/year,"
            f" USD {salary['usd_year']:,.0f}/year)")
    return {"confirmed": True, "text": text, "sources": list(salary.get("sources", []))}


def build_kit(master: dict, tailored: dict, posting, salary: dict | None, *,
              slug: str, files: dict[str, str]) -> dict:
    """The kit.json document. `files` maps cv_pdf and letter_pdf to file names that exist."""
    view = build_cv_view(tailored, master)
    note = tailored.get("recruiter_note")
    return {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "lang": tailored["lang"],
        "company": posting.company,
        "role": posting.title,
        "links": {"apply": posting.apply_url or posting.url, "posting": posting.url,
                  "cv_pdf": files.get("cv_pdf"), "letter_pdf": files.get("letter_pdf")},
        "fields": _fields(master),
        "work": _work(master, tailored),
        "education": [{"key": f"education.{n}", **e} for n, e in enumerate(view["education"])],
        "languages": [{"key": f"languages.{n}", **e} for n, e in enumerate(view["languages"])],
        "certificates": [{"key": f"certificates.{n}", **e} for n, e in enumerate(view["certificates"])],
        "salary": _salary(salary, slug),
        "answers": [{"question": a["question"], "answer": a["answer"], "limit": a.get("limit")}
                    for a in tailored.get("answers", [])],
        "recruiter_note": {"connect": note["connect"], "message": note["message"]} if note else None,
        "tracker": [f"cvforge track status {slug} applied",
                    f"cvforge track stage {slug} <name> --kind interview --due YYYY-MM-DD"],
    }

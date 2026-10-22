"""Knock-out facts (visa, years, languages, relocation, notice, location), master only."""
from __future__ import annotations

from cvforge.profile.model import localized

PT = ("pt-BR", "pt-PT")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def years_text(months: int, lang: str) -> str:
    years, rest = divmod(months, 12)
    if lang in PT:
        parts = [_plural(years, "ano", "anos")] if years else []
        if rest or not years:
            parts.append(_plural(rest, "mês", "meses"))
        return " e ".join(parts)
    parts = [_plural(years, "year", "years")] if years else []
    if rest or not years:
        parts.append(_plural(rest, "month", "months"))
    return " ".join(parts)


def knockout_facts(master: dict, months: int, lang: str) -> dict[str, str]:
    prefs = master.get("x-preferences") or {}
    loc = (master.get("basics") or {}).get("location") or {}
    languages = "; ".join(
        f"{localized(x['language'], lang, item_id=x['id'])}: "
        f"{localized(x['fluency'], lang, item_id=x['id'])}"
        for x in master.get("languages", []) if x.get("fluency"))
    yes, no = ("sim", "não") if lang in PT else ("yes", "no")
    return {
        "visa": "; ".join(f"{k}: {v}" for k, v in (prefs.get("visa") or {}).items()),
        "years": years_text(months, lang),
        "languages": languages,
        "relocation": yes if prefs.get("relocation") else no,
        "notice": prefs.get("noticePeriod", ""),
        "location": ", ".join(
            str(loc[k]) for k in ("city", "region", "countryCode") if loc.get(k)),
    }

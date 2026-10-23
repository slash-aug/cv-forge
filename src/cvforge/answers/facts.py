"""Knock-out facts (visa, years, languages, relocation, notice, location), master only."""
from __future__ import annotations

from cvforge.profile.model import localized

PT = ("pt-BR", "pt-PT")
ACRONYMS = {"eu": "EU", "uk": "UK", "us": "US", "usa": "USA", "cplp": "CPLP"}


def _visa_name(key: str) -> str:
    """A master key such as `eu_blue_card` as a name ("EU Blue Card"); keys with capitals stay as written."""
    if key != key.lower():
        return key
    return " ".join(ACRONYMS.get(w, w.capitalize()) for w in key.replace("-", "_").split("_") if w)


def visa_text(visa) -> str:
    """x-preferences.visa as one readable line: "EU Blue Card: eligible; Portugal: CPLP mobility"."""
    if isinstance(visa, dict):
        return "; ".join(f"{_visa_name(str(k))}: {v}" for k, v in visa.items())
    return str(visa or "")


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
        "visa": visa_text(prefs.get("visa")),
        "years": years_text(months, lang),
        "languages": languages,
        "relocation": yes if prefs.get("relocation") else no,
        "notice": prefs.get("noticePeriod", ""),
        "location": ", ".join(
            str(loc[k]) for k in ("city", "region", "countryCode") if loc.get(k)),
    }

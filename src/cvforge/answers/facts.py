"""Knock-out facts (visa, years, languages, relocation, notice, location), master only."""
from __future__ import annotations

from datetime import date

from cvforge.apply.ie_permits import load_permit_table
from cvforge.apply.ireland import route_for
from cvforge.profile.model import localized
from cvforge.profile.prefs import degree_recognised, self_apply

PT = ("pt-BR", "pt-PT")
ACRONYMS = {"eu": "EU", "uk": "UK", "us": "US", "usa": "USA", "cplp": "CPLP",
            "csep": "CSEP", "gep": "GEP", "soc": "SOC"}


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


CSOL_NOTE = " This role is on the Critical Skills Occupations List, so no labour market test is needed."
SELF_APPLY = " If it helps, I can apply for the permit myself."


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get("en") or next(iter(value.values()), ""))
    return str(value or "")


def _english(master: dict) -> str:
    """The EF SET certificate name, else the master English fluency. Never a made-up score."""
    for cert in master.get("certificates") or []:
        name = _text(cert.get("name"))
        if "EF SET" in name:
            return name
    for item in master.get("languages") or []:
        if _text(item.get("language")).casefold() == "english" and item.get("fluency"):
            return _text(item["fluency"])
    return ""


def ireland_facts(master: dict, ireland: dict, lang: str) -> dict[str, str]:
    """Answers for an Irish form: sponsorship, right to work, English. Master facts only."""
    # Never trust the stored route for a CSEP claim: recompute it from salary, SOC and degree.
    route = route_for(ireland.get("salary_eur_year"), ireland.get("soc"),
                      degree_recognised(master), load_permit_table(date.today())[0])
    on_csol = bool(ireland.get("on_csol"))
    if route == "csep":
        text = "Yes. I will need a Critical Skills Employment Permit."
    else:
        text = "Yes. I will need an employment permit."
    if on_csol:
        text += CSOL_NOTE
    silent = ireland.get("permit_record") is None or bool(ireland.get("sponsorship_silent"))
    if self_apply(master) and silent:
        text += SELF_APPLY
    return {"sponsorship": text,
            "right_to_work": "No, an employment permit is required.",
            "english": _english(master)}

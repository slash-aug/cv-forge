"""The Irish CV and letter variant: permit line, relocation label, references, spelling."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from cvforge.apply.check import REGIONS
from cvforge.apply.ie_permits import load_permit_table
from cvforge.apply.ireland import claims_csep
from cvforge.profile.prefs import degree_recognised, self_apply, work_rights

REFERENCES = "References available on request"
SELF_APPLY = " If it helps, I can apply for the permit myself."


@dataclass(frozen=True)
class Region:
    code: str
    permit_line: str
    location_label: str | None
    references: bool
    spelling: bool
    permit_note: str = ""  # the letter's final paragraph; empty for no note


def _permit_line(master: dict, ireland: dict | None, today: date | None) -> str:
    rights = work_rights(master, "IE") or {}
    if rights.get("status") != "needs-permit":
        return ""
    ireland = ireland or {}
    soc = ireland.get("soc") or next(iter(rights.get("soc") or []), None)
    table = load_permit_table(today or date.today())[0]
    on_csol = bool(ireland["on_csol"]) if "on_csol" in ireland and ireland.get("soc") \
        else soc in table.csol_soc
    # The verdict must say csep and the recompute from the lowest posted salary must agree:
    # a stale, edited or fixed-term-downgraded verdict never becomes a CSEP claim.
    if claims_csep(ireland, degree_recognised(master), table):
        return f"Eligible for Critical Skills Employment Permit (SOC {soc})"
    if on_csol:
        return "Requires employment permit (Critical Skills occupation)"
    return "Requires employment permit sponsorship"


_COUNTRY = {"ie", "ireland", "republic of ireland"}
CITIES = tuple(t for t in REGIONS["ireland"] if t not in _COUNTRY)
_CITY = re.compile(r"\b(" + "|".join(CITIES) + r")\b", re.IGNORECASE)


def irish_city(req: dict) -> str | None:
    """The first Irish city named in the location quote, else in job_countries."""
    location = req.get("location") or {}
    for text in (location.get("quote") or "", *(location.get("job_countries") or [])):
        m = _CITY.search(text)
        if m:
            return m.group().title()
    return None


def ireland_region(master: dict, *, city: str | None, ireland: dict | None,
                   today: date | None = None) -> Region:
    """The IE region from master facts and the verdict's ireland block (None: no verdict)."""
    line = _permit_line(master, ireland, today)
    relocation = bool((master.get("x-preferences") or {}).get("relocation"))
    label = None
    if relocation:
        label = f"Relocating to {city}, Ireland" if city else "Relocating to Ireland"
    note = ""
    if line:
        silent = ireland is None or ireland.get("permit_record") is None \
            or bool(ireland.get("sponsorship_silent"))
        note = line + "." + (SELF_APPLY if self_apply(master) and silent else "")
    return Region("IE", line, label, True, True, note)


def skill_keywords(master: dict) -> frozenset[str]:
    return frozenset(k for s in master.get("skills") or [] for k in s.get("keywords") or [])


_Z_STEMS = ("organi", "optimi", "analy", "prioriti", "standardi", "moderni")
_Z_ENDINGS = ("ze", "zed", "zes", "zing", "zer", "zers", "zation", "zations")
SPELLING = {stem + end: stem + end.replace("z", "s", 1) for stem in _Z_STEMS for end in _Z_ENDINGS}
SPELLING.update({
    "center": "centre", "centers": "centres", "centered": "centred",
    "color": "colour", "colors": "colours", "colored": "coloured", "coloring": "colouring",
    "behavior": "behaviour", "behaviors": "behaviours", "behavioral": "behavioural",
    "catalog": "catalogue", "catalogs": "catalogues", "cataloged": "catalogued",
    "cataloging": "cataloguing",
})
_WORD = re.compile(r"\b(" + "|".join(sorted(SPELLING, key=len, reverse=True)) + r")\b",
                   re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+", re.IGNORECASE)


def _case_like(source: str, word: str) -> str:
    if source.isupper():
        return word.upper()
    if source[0].isupper():
        return word[0].upper() + word[1:]
    return word


def irish_spelling(text: str, keep: frozenset[str] = frozenset()) -> str:
    """US to Irish/UK spelling; URLs and the `keep` skill keywords are never changed."""
    spans = [m.span() for m in _URL.finditer(text)]
    for keyword in keep:
        pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
        spans.extend(m.span() for m in re.finditer(pattern, text, re.IGNORECASE))

    def swap(m: re.Match) -> str:
        if any(a <= m.start() < b for a, b in spans):
            return m.group()
        return _case_like(m.group(), SPELLING[m.group().lower()])

    return _WORD.sub(swap, text)


__all__ = ["REFERENCES", "Region", "ireland_region", "irish_city", "irish_spelling", "skill_keywords"]

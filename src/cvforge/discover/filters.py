"""Pure filters that decide market, role type, seniority, sponsorship and stack fit.

No I/O. Every call here is a judgment about one fetched job. The guiding
principle: a wrongly dropped role costs more than one extra row, so when a
rule is ambiguous the role is kept.

Matching rules (all calls)
- Text is folded for case and accents (`text.fold_accents`). Word boundaries
  treat `.`, `+` and `#` as word characters, so `Node.js`, `C#` and `C++`
  match whole. A trailing sentence period does not block a match.

market_of(location, workplace, description, home)
- IE: the location names Ireland, an Irish place (IRISH_PLACES), or `IE` as a
  whole word (case-sensitive, location only, never the description).
- IE also when the role is remote and the location names Ireland, EMEA,
  Europe, EU or UK & Ireland. A remote role is one with workplace "remote" or
  the word "remote" in the location.
- BR: the location names Brazil, Brasil, `BR` (case-sensitive) or a place in
  BRAZIL_PLACES, but only when the role is remote or in Londrina. A Brazilian
  on-site or hybrid role elsewhere gives None.
- Bare remote (location empty, Remote, Anywhere or Worldwide): the region is
  read from the description with the same terms. No region found gives
  (home, True). A remote role restricted elsewhere (Remote - US) gives None.
- A location naming both markets gives IE.

is_software(title)
- Needs a software word (engineer, developer, frontend, ...). Excluded by
  sales, support, hardware and similar words, and by "quality assurance"
  without "software". A title with "software" is never excluded by the other
  words (keeps "Software Engineer, Customer Tools").

is_senior(title, description)
- Title has a whole word from SENIOR_WORDS, a roman level III or above, or
  L5/E5 and up. "team lead" is removed first. "Leadership", "Staffing" and
  "Seniority" do not match.
- Description asks for at least 5 years in a clear phrase ("5+ years",
  "5 or more years", "at least 6 years", "minimum (of) 7 years", "min. 5
  years", "5+ anos", "no minimo 5 anos", "pelo menos 5 anos"). A range such
  as "3-5 years" uses its lower bound. A bare "5 years" is not a phrase.

refuses_sponsorship(text)
- Returns the matched phrase for a refusal or for a requirement of existing
  work rights (SPONSOR_REFUSALS), else None.

stack_fit(text, keywords)
- match: 3 or more distinct master keywords. partial: 1 or 2, or 0 with no
  foreign-stack term. misaligned: 0 and at least one FOREIGN_STACK term (a
  term that is also a master keyword is ignored). Keywords of 3 characters or
  fewer match case-sensitively. No fuzzy spelling: "nodejs" is not "Node.js".
  Matched keywords come back in keyword-list order, de-duplicated.
"""

from __future__ import annotations

import re

from cvforge.text import fold_accents

IRISH_PLACES = (
    "dublin", "cork", "galway", "limerick", "waterford", "kilkenny", "athlone",
    "sligo", "drogheda", "dundalk", "wexford", "letterkenny", "shannon",
)
BRAZIL_PLACES = (
    # capitals
    "sao paulo", "rio de janeiro", "curitiba", "belo horizonte", "porto alegre",
    "florianopolis", "londrina", "brasilia",
    # states
    "parana", "minas gerais", "santa catarina", "rio grande do sul",
)
IE_REMOTE_TERMS = ("ireland", "emea", "europe", "eu", "uk & ireland")
BR_COUNTRY_TERMS = ("brazil", "brasil")

SENIOR_WORDS = (
    "senior", "sr", "staff", "principal", "lead", "head", "director", "manager",
    "architect", "distinguished", "vp", "chief", "senior", "lider", "gerente",
    "coordenador", "arquiteto", "especialista",
)

FOREIGN_STACK = (
    "embedded", "firmware", "rtos", "fpga", "verilog", "vhdl", "swift", "swiftui",
    "objective-c", "salesforce", "apex", "abap", "sap", "cobol", "mainframe",
    "plc", "unity3d", "unreal engine",
)

_RIGHTS_PLACE = r"(?:ireland|the\s+eu|the\s+eea|europe|eu|eea)"
SPONSOR_REFUSALS = (
    (
        r"\b(?:unable\s+to|not\s+able\s+to|cannot|can't|can\s+not|do\s+not|does\s+not"
        r"|don't|doesn't|will\s+not|won't)\s+(?:\w+\s+)?sponsor"
    ),
    r"\bno\s+(?:visa\s+|work\s+permit\s+)?sponsorship",
    r"\bsponsorship\s+(?:is\s+|are\s+)?(?:not\s+(?:available|offered|provided)|unavailable)",
    r"\bnot\s+(?:able\s+to\s+)?offer(?:ing)?\s+(?:visa\s+)?sponsorship",
    rf"\bmust\s+(?:already\s+)?have\s+(?:the\s+)?(?:full\s+)?right\s+to\s+work\s+in\s+{_RIGHTS_PLACE}",
    rf"\bmust\s+be\s+eligible\s+to\s+work\s+in\s+{_RIGHTS_PLACE}\s+without\s+(?:visa\s+)?sponsorship",
    r"\beu\s+citizens\s+only",
    r"\bstamp\s*4\s+required",
)

_SOFTWARE_WORDS = (
    r"engineers?|engineering|developers?|programmers?|programmatore|software"
    r"|full[\s-]?stack|front[\s-]?end|back[\s-]?end|web|desenvolvedor(?:a|es|as)?"
    r"|programador(?:a|es|as)?|engenheiro(?:s|a|as)?|dev"
)
_NOT_SOFTWARE = (
    "sales", "solutions", "solution", "support", "customer", "field", "network",
    "hardware", "mechanical", "electrical", "civil", "manufacturing", "process",
)


def _norm(text: str) -> str:
    return fold_accents((text or "").replace("’", "'"))


def _term(term: str) -> re.Pattern[str]:
    """Whole-term pattern where `.`, `+` and `#` count as word characters."""
    return re.compile(r"(?<![\w.+#])" + re.escape(term) + r"(?![\w+#])(?!\.\w)")


def _has(folded: str, term: str) -> bool:
    return _term(term).search(folded) is not None


def _any(folded: str, terms: tuple[str, ...]) -> bool:
    return any(_has(folded, t) for t in terms)


def _mentions_ie(folded: str) -> bool:
    return _any(folded, IE_REMOTE_TERMS + IRISH_PLACES)


def _mentions_br(folded: str) -> bool:
    return _any(folded, BR_COUNTRY_TERMS + BRAZIL_PLACES)


def market_of(
    location: str, workplace: str | None, description: str, home: str
) -> tuple[str | None, bool]:
    raw = location or ""
    loc = _norm(raw)
    remote = (workplace or "").lower() == "remote" or _has(loc, "remote")

    ie_named = (
        _has(loc, "ireland")
        or _any(loc, IRISH_PLACES)
        or re.search(r"(?<![\w.])IE(?![\w.])", raw) is not None
    )
    if ie_named:
        return "IE", False
    if remote and _any(loc, IE_REMOTE_TERMS):
        return "IE", False

    br_named = _mentions_br(loc) or re.search(r"(?<![\w.])BR(?![\w.])", raw) is not None
    if br_named:
        if remote or _has(loc, "londrina"):
            return "BR", False
        return None, False

    if not remote:
        return None, False

    rest = re.sub(r"\b(?:remote|anywhere|worldwide)\b", " ", loc)
    if re.search(r"\w", rest):
        return None, False  # restricted elsewhere, e.g. Remote - US

    desc = _norm(description)
    if _mentions_ie(desc):
        return "IE", False
    if _mentions_br(desc):
        return "BR", False
    return home, True


def is_software(title: str) -> bool:
    folded = _norm(title)
    if not re.search(rf"(?<![\w.+#])(?:{_SOFTWARE_WORDS})(?![\w+#])", folded):
        return False
    if _has(folded, "software"):
        return True
    if _any(folded, _NOT_SOFTWARE) or re.search(r"\brecruit", folded):
        return False
    return "quality assurance" not in folded


_LEVEL_SUFFIX = re.compile(r"(?<![\w.+#])(?:iii|iv|v|vi|vii|viii|ix|[le](?:[5-9]|\d\d))(?![\w+#])")
_UNIT = r"(?:years?|yrs?|anos?)"
_RANGE = re.compile(rf"(\d{{1,2}})\s*(?:-|to|a)\s*\d{{1,2}}\s*\+?\s*{_UNIT}\b")
_YEARS_PATTERNS = (
    re.compile(rf"(\d{{1,2}})\s*\+\s*{_UNIT}\b"),
    re.compile(rf"(\d{{1,2}})\s+or\s+more\s+{_UNIT}\b"),
    re.compile(
        rf"(?:at\s+least|minimum(?:\s+of)?|min\.?|no\s+minimo|pelo\s+menos)\s+(\d{{1,2}})\s*\+?\s*{_UNIT}\b"
    ),
)


def _years_required(description: str) -> int:
    folded = _norm(description)
    lows = [int(m.group(1)) for m in _RANGE.finditer(folded)]
    rest = _RANGE.sub(" ", folded)
    for pat in _YEARS_PATTERNS:
        lows.extend(int(m.group(1)) for m in pat.finditer(rest))
    return max(lows, default=0)


def is_senior(title: str, description: str) -> bool:
    folded = _norm(title).replace("team lead", " ")
    if _any(folded, SENIOR_WORDS) or _LEVEL_SUFFIX.search(folded):
        return True
    return _years_required(description) >= 5


_REFUSAL_RES = tuple(re.compile(p) for p in SPONSOR_REFUSALS)


def refuses_sponsorship(text: str) -> str | None:
    folded = _norm(text)
    for pat in _REFUSAL_RES:
        m = pat.search(folded)
        if m:
            return m.group(0)
    return None


def master_keywords(master: dict) -> list[str]:
    seen: dict[str, None] = {}
    for skill in master.get("skills") or []:
        for kw in (skill or {}).get("keywords") or []:
            if isinstance(kw, str) and kw.strip():
                seen.setdefault(kw.strip(), None)
    return list(seen)


def _keyword_hit(kw: str, raw: str, folded: str) -> bool:
    if len(kw) <= 3:
        return _term(kw).search(raw) is not None
    return _has(folded, fold_accents(kw))


def stack_fit(text: str, keywords: list[str]) -> tuple[str, list[str]]:
    raw = text or ""
    folded = _norm(raw)
    matched: list[str] = []
    for kw in keywords:
        if kw not in matched and _keyword_hit(kw, raw, folded):
            matched.append(kw)
    if len(matched) >= 3:
        return "match", matched
    if matched:
        return "partial", matched
    own = {fold_accents(k) for k in keywords}
    foreign = [t for t in FOREIGN_STACK if t not in own and _has(folded, t)]
    return ("misaligned" if foreign else "partial"), matched

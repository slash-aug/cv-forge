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
  Europe, EU or UK & Ireland. A remote role is one with workplace "remote",
  or "remote", "home based", "home-based", "work from home" or "wfh" in the
  location.
- IE also when one alternative of the location (split on "or", "/", ";",
  "|") names only EMEA, Europe or EU ("EMEA", "Europe or US"), remote or not.
- Dublin in the US ("US-CA-Dublin", "Dublin, CA", "Dublin, California",
  "Dublin, Ohio") is not an Irish place.
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
  L5/E5 and up. "team lead" and "member of technical staff" are removed
  first (the latter is a software title, not a senior one). "Leadership", "Staffing" and
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
  fewer, and all-caps keywords ("SOLID", "REST"), match case-sensitively. No fuzzy spelling: "nodejs" is not "Node.js".
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
IE_REGIONS = frozenset({"emea", "europe", "eu"})
US_STATES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
})
MTS = "member of technical staff"
BR_COUNTRY_TERMS = ("brazil", "brasil")

SENIOR_WORDS = (
    "senior", "sr", "staff", "principal", "lead", "head", "director", "manager",
    "architect", "distinguished", "vp", "chief", "lider", "gerente",
    "coordenador", "arquiteto", "especialista",
)

# Unambiguous foreign-stack terms make a role misaligned on their own.
FOREIGN_STACK_STRONG = (
    "firmware", "rtos", "fpga", "verilog", "vhdl", "swiftui", "objective-c",
    "salesforce", "abap", "cobol", "mainframe", "unity3d", "unreal engine",
)
# Ambiguous words ("Acme PLC", "Apex Group") count only alongside another term.
FOREIGN_STACK_WEAK = ("embedded", "swift", "apex", "sap", "plc")
FOREIGN_STACK = FOREIGN_STACK_STRONG + FOREIGN_STACK_WEAK

# Words that put no restriction on a remote role's region.
REMOTE_NOISE = frozenset({
    "remote", "global", "fully", "first", "worldwide", "anywhere", "hybrid",
    "international", "home", "based", "wfh", "in", "the", "world", "work", "from",
    "any", "location", "flexible",
})

_RIGHTS_PLACE = r"(?:ireland|the\s+eu|the\s+eea|europe|eu|eea)"
SPONSOR_REFUSALS = (
    (
        r"\b(?:unable\s+to|not\s+able\s+to|cannot|can't|can\s+not|do\s+not|does\s+not"
        r"|don't|doesn't|will\s+not|won't)\s+"
        r"(?:(?:currently|typically|generally|normally|offer|provide)\s+)?sponsor"
    ),
    r"\bno\s+(?:visa\s+|work\s+permit\s+)?sponsorship\s+(?:is\s+)?(?:available|offered|provided)",
    r"\bno\s+visa\s+sponsorship\b",
    r"\bsponsorship\s+(?:is\s+|are\s+)?(?:not\s+(?:available|offered|provided)|unavailable)",
    r"\bnot\s+(?:able\s+to\s+)?offer(?:ing)?\s+(?:visa\s+)?sponsorship",
    rf"\bmust\s+(?:already\s+)?have\s+(?:the\s+)?(?:full\s+)?right\s+to\s+work\s+in\s+{_RIGHTS_PLACE}",
    rf"\bmust\s+be\s+eligible\s+to\s+work\s+in\s+{_RIGHTS_PLACE}\s+without\s+(?:visa\s+)?sponsorship",
    r"\beu\s+citizens\s+only",
    r"\bstamp\s*4\s+required",
)

_STRONG_WORDS = (
    r"member\s+of\s+technical\s+staff|developers?|programmers?|programmatore|software|full[\s-]?stack"
    r"|front[\s-]?end|back[\s-]?end|desenvolvedor(?:a|es|as)?|programador(?:a|es|as)?"
)
_WEAK_WORDS = r"engineers?|engineering|web|dev|engenheiro(?:s|a|as)?"
_NOT_SOFTWARE = (
    "sales", "solutions", "solution", "support", "customer", "field", "network",
    "hardware", "mechanical", "electrical", "civil", "manufacturing", "process",
)


def _norm(text: str) -> str:
    """Folded text with whitespace runs collapsed (also bounds regex work)."""
    return re.sub(r"\s+", " ", fold_accents((text or "").replace("\u2019", "'")))


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


_US_DUBLIN = re.compile(
    r"\bUS-[A-Z]{2}-Dublin\b|\bDublin\s*,\s*(?:([A-Z]{2})\b|California\b|Ohio\b)", re.IGNORECASE
)
_HOME_BASED = re.compile(r"\bhome[\s-]based\b|\bwork from home\b|\bwfh\b")


def _drop_us_dublin(raw: str) -> str:
    def repl(m: re.Match[str]) -> str:
        state = m.group(1)
        return " " if state is None or state in US_STATES else m.group(0)
    return _US_DUBLIN.sub(repl, raw)


def _region_only(loc: str) -> bool:
    """True when one alternative of the location names only EMEA, Europe or EU."""
    for part in re.split(r"\s+or\s+|[/;|]", loc):
        words = [t for t in re.findall(r"[a-z]+", part) if t not in REMOTE_NOISE]
        if words and all(t in IE_REGIONS for t in words):
            return True
    return False


def market_of(
    location: str, workplace: str | None, description: str, home: str
) -> tuple[str | None, bool]:
    raw = _drop_us_dublin(location or "")
    loc = _norm(raw)
    tokens = re.findall(r"[a-z]+", loc)
    remote = (
        (workplace or "").lower() == "remote"
        or _has(loc, "remote")
        or _HOME_BASED.search(loc) is not None
        or (bool(tokens) and all(t in ("anywhere", "worldwide", "global") for t in tokens))
    )

    ie_named = (
        _has(loc, "ireland")
        or _any(loc, IRISH_PLACES)
        or re.search(r"(?<![\w.])IE(?![\w.])", raw) is not None
    )
    if ie_named:
        return "IE", False
    if (remote and _any(loc, IE_REMOTE_TERMS)) or _region_only(loc):
        return "IE", False

    br_named = _mentions_br(loc) or re.search(r"(?<![\w.])BR(?![\w.])", raw) is not None
    if br_named:
        if remote or _has(loc, "londrina"):
            return "BR", False
        return None, False

    if not remote:
        return None, False

    if any(t not in REMOTE_NOISE for t in re.findall(r"[a-z]+", loc)):
        return None, False  # restricted elsewhere, e.g. Remote - US

    desc = _norm(description)
    if _mentions_ie(desc):
        return "IE", False
    if _mentions_br(desc):
        return "BR", False
    return home, True


def is_software(title: str) -> bool:
    folded = _norm(title)
    if re.search(rf"(?<![\w.+#])(?:{_STRONG_WORDS})(?![\w+#])", folded):
        return True
    if not re.search(rf"(?<![\w.+#])(?:{_WEAK_WORDS})(?![\w+#])", folded):
        return False
    if _any(folded, _NOT_SOFTWARE) or re.search(r"\brecruit", folded):
        return False
    return "quality assurance" not in folded


_LEVEL_SUFFIX = re.compile(r"(?<![\w.+#])(?:iii|iv|vi|vii|viii|ix|[le](?:[5-9]|\d\d))(?![\w+#])")
_LEVEL_V = re.compile(r"(?<![\w.+#])(?:engineer|developer|programmer|analyst|scientist) v(?![\w+#])")
_UNIT = r"(?:years?|yrs?|anos?)"
_NOT_EXPERIENCE = r"(?!\s+(?:old|of\s+age|in\s+business|of\s+history|in\s+the\s+market))"
_RANGE = re.compile(rf"(\d{{1,2}})\s*(?:-|to|a)\s*\d{{1,2}}\s*(?:\+\s*)?{_UNIT}\b{_NOT_EXPERIENCE}")
_YEARS_PATTERNS = (
    re.compile(rf"(\d{{1,2}})\s*\+\s*{_UNIT}\b{_NOT_EXPERIENCE}"),
    re.compile(rf"(\d{{1,2}})\s+or\s+more\s+{_UNIT}\b{_NOT_EXPERIENCE}"),
    re.compile(
        rf"(?:at\s+least|minimum(?:\s+of)?|min\.?|no\s+minimo|pelo\s+menos)\s+(\d{{1,2}})\s*(?:\+\s*)?{_UNIT}\b{_NOT_EXPERIENCE}"
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
    folded = _norm(title).replace("team lead", " ").replace(MTS, " ")
    if _any(folded, SENIOR_WORDS) or _LEVEL_SUFFIX.search(folded) or _LEVEL_V.search(folded):
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
    if len(kw) <= 3 or kw.isupper():
        return _term(kw).search(raw) is not None
    return _has(folded, fold_accents(kw))


def stack_fit(text: str, keywords: list[str]) -> tuple[str, list[str]]:
    raw = re.sub(r"\s+", " ", text or "")
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
    strong = [t for t in FOREIGN_STACK_STRONG if t not in own and _has(folded, t)]
    weak = [t for t in FOREIGN_STACK_WEAK if t not in own and _has(folded, t)]
    misaligned = bool(strong) or len(weak) >= 2
    return ("misaligned" if misaligned else "partial"), matched

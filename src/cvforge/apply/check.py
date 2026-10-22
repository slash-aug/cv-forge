"""Eligibility rules applied to a validated requirements.yaml (spec 7.3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from cvforge.apply.experience import engineering_months, years_limit
from cvforge.apply.posting import Posting
from cvforge.money.normalise import Money, monthly, pj_equivalent
from cvforge.money.rates import MoneyError, Rates
from cvforge.text import fold_accents

REGIONS = {
    "brazil": ("br", "brazil", "brasil"),
    "portugal": ("pt", "portugal"),
    "latam": ("latam", "latin america", "south america", "americas", "south and central america"),
    "worldwide": ("worldwide", "anywhere", "global", "remote (global)", "international"),
}
TOKEN_REGION = {token: region for region, tokens in REGIONS.items() for token in tokens}
HOME = {"brazil", "portugal"}
OPEN = {"latam", "worldwide"}

LANG_NAMES = {
    "en": ("English", "english", "ingles"),
    "pt": ("Portuguese", "portuguese", "portugues"),
    "es": ("Spanish", "spanish", "espanol", "espanhol", "castellano"),
    "fr": ("French", "french", "francais", "frances"),
    "it": ("Italian", "italian", "italiano"),
    "de": ("German", "german", "deutsch", "alemao"),
    "nl": ("Dutch", "dutch", "nederlands", "holandes"),
    "ro": ("Romanian", "romanian"),
    "ca": ("Catalan", "catalan"),
    "sv": ("Swedish", "swedish"),
    "da": ("Danish", "danish"),
    "no": ("Norwegian", "norwegian"),
    "pl": ("Polish", "polish"),
    "ru": ("Russian", "russian"),
    "uk": ("Ukrainian", "ukrainian"),
    "cs": ("Czech", "czech"),
}
NAME_CODE = {name: code for code, names in LANG_NAMES.items() for name in names[1:]}
FAMILIES = ({"pt", "es", "fr", "it", "ro", "ca"}, {"en", "de", "nl", "sv", "da", "no"},
            {"pl", "ru", "uk", "cs"})
CEFR = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6}
LEVEL_WORDS = (("native", 7), ("mother tongue", 7), ("bilingual", 7), ("nativo", 7),
               ("proficient", 6), ("fluent", 5), ("fluente", 5), ("advanced", 5),
               ("upper intermediate", 4), ("intermediate", 3), ("basic", 2),
               ("elementary", 2), ("beginner", 1))
CEFR_TOKEN = re.compile(r"\b([abc][12])\b")


@dataclass(frozen=True)
class RuleResult:
    rule: str
    ok: bool
    message: str
    quote: str | None


@dataclass
class Verdict:
    passed: bool
    results: list[RuleResult]
    warnings: list[str] = field(default_factory=list)


def _fold(text: str) -> str:
    return " ".join(fold_accents(text).split())


def region_class(token: str) -> str:
    return TOKEN_REGION.get(_fold(token), "other")


HOME_WORD = re.compile(r"\b(brasil|brazil|br|portugal|pt)\b")


def home_named(quote: str | None) -> set[str]:
    """Brazil and Portugal as named in a quote ("must reside in Brazil" names his own country)."""
    return {region_class(w) for w in HOME_WORD.findall(_fold(quote or ""))} & HOME


# Rule 1: years


def _years(req: dict, master: dict, today: date) -> RuleResult:
    required = [y for y in req.get("years") or [] if y["kind"] == "required"]
    if not required:
        return RuleResult("years", True, "no years stated", None)
    top = max(required, key=lambda y: y["min"])
    months = engineering_months(master, today)
    limit = years_limit(months)
    message = f"{top['min']:g}+ required; limit {limit} ({months} months of engineering)"
    return RuleResult("years", top["min"] <= limit, message, top["quote"])


# Rule 2: location, spec 7.3 order 1 to 7


def _location(req: dict, company: dict | None) -> RuleResult:
    loc, sponsorship = req["location"], req["sponsorship"]
    workplace = loc["workplace"]
    remote = workplace == "remote"
    countries = {region_class(t) for t in loc.get("job_countries") or []}
    allowed = {region_class(t) for t in loc.get("allowed") or []}

    def result(ok: bool, message: str, quote: str | None = None) -> RuleResult:
        return RuleResult("location", ok, message, quote or loc.get("quote"))

    if sponsorship["status"] == "refused":
        # Rule 1 skips only a requirement for a country he is not in: a residence or work-right
        # requirement that names Brazil or Portugal limits the job to his own country.
        home = home_named(sponsorship.get("quote"))
        if not home:
            return result(False, "sponsorship or right to work refused", sponsorship.get("quote"))
        return result(True, f"{workplace} job requiring residence or work rights in "
                            f"{' or '.join(sorted(h.title() for h in home))}",
                      sponsorship.get("quote"))
    if countries & HOME or (remote and allowed & HOME):
        return result(True, f"{workplace} job in Brazil or Portugal")
    if remote and allowed & OPEN:
        return result(True, "remote, open to Latin America or worldwide")
    if sponsorship["status"] == "offered":
        return result(True, "relocation or visa support offered", sponsorship.get("quote"))
    if remote and allowed:
        return result(False, f"remote limited to {', '.join(loc['allowed'])}")
    where = "remote with no region stated" if remote else f"{workplace} abroad"
    if company and company.get("sponsor"):
        types = ", ".join(s["type"] for s in company["sponsor"])
        return result(True, f"{where}; {company['name']} has a sponsor mark ({types})")
    return result(False, f"{where}, no sponsorship stated and no sponsor mark")


# Rule 3: salary


def _salary(req: dict, master: dict, rates: Rates | None, clt_factor: float) -> RuleResult:
    salary = req.get("salary") or {}
    amount = salary.get("max") if salary.get("max") is not None else salary.get("min")
    if amount is None:
        return RuleResult("salary", True, "no salary stated", None)
    floor = (master.get("x-preferences") or {}).get("payFloor")
    if not floor:
        return RuleResult("salary", True, "no pay floor set", salary.get("quote"))
    if rates is None:
        raise MoneyError("currency rates are needed for the salary rule")
    contract = (salary.get("contract") or "unknown").lower()
    which = "max" if salary.get("max") is not None else "min"
    offered = pj_equivalent(
        monthly(Money(amount, salary["currency"].upper(), salary["period"]), "BRL", rates),
        contract, clt_factor)
    floor_brl = monthly(Money(floor["amount"], floor["currency"].upper(), floor["period"]),
                        "BRL", rates)
    basis = f" ({contract.upper()} x {clt_factor:g})" if contract == "clt" else ""
    message = (f"{which} {amount:g} {salary['currency'].upper()}/{salary['period']}{basis} is "
               f"{offered:,.0f} BRL/month against a floor of {floor_brl:,.0f} BRL/month")
    return RuleResult("salary", offered >= floor_brl, message, salary.get("quote"))


# Rule 4: languages


def _lang_code(name: str) -> str:
    folded = _fold(name)
    head = re.split(r"[-_ ]", folded)[0]
    if head in LANG_NAMES:
        return head
    return NAME_CODE.get(folded) or NAME_CODE.get(head) or folded


def _lang_name(code: str, given: str) -> str:
    return LANG_NAMES[code][0] if code in LANG_NAMES else given


def _rank(level: str | None) -> int | None:
    if not level:
        return None
    folded = _fold(level)
    match = CEFR_TOKEN.search(folded)
    if match:
        return CEFR[match.group(1)]
    return next((rank for word, rank in LEVEL_WORDS if word in folded), None)


def _texts(value) -> list[str]:
    return [value] if isinstance(value, str) else list(value.values())


def _known_languages(master: dict) -> list[dict]:
    known = []
    for item in master.get("languages") or []:
        names = _texts(item["language"])
        codes = {_lang_code(n) for n in names}
        code = next((c for c in codes if c in LANG_NAMES), _lang_code(names[0]))
        fluency = item["fluency"] if isinstance(item["fluency"], str) else (
            item["fluency"].get("en") or next(iter(item["fluency"].values())))
        rank = _rank(item.get("cefr")) or _rank(fluency)
        shown = item.get("cefr") or fluency.lower()
        known.append({"code": code, "name": _lang_name(code, names[0]), "rank": rank,
                      "label": f"{_lang_name(code, names[0])} ({shown})"})
    return known


def _closest(code: str, known: list[dict]) -> dict:
    family = next((f for f in FAMILIES if code in f), set())
    pool = [k for k in known if k["code"] in family] or known
    return max(pool, key=lambda k: k["rank"] or 0)


def _languages(req: dict, master: dict) -> tuple[RuleResult, list[str]]:
    wanted = req.get("languages_required") or []
    if not wanted:
        return RuleResult("languages", True, "no languages required", None), []
    known = _known_languages(master)
    warnings, quotes = [], []
    for item in wanted:
        code = _lang_code(item["lang"])
        level = item.get("level")
        label = _lang_name(code, item["lang"]) + (f" {level}" if level else "")
        have = next((k for k in known if k["code"] == code), None)
        if have is None:
            if not known:
                warnings.append(f"{label} required; no languages in the master profile")
            else:
                warnings.append(f"{label} required; you have {_closest(code, known)['label']}")
            quotes.append(item["quote"])
        elif level:
            need, rank = _rank(level), have["rank"]
            if need is None or rank is None or need > rank:
                warnings.append(f"{label} required; you have {have['label']}")
                quotes.append(item["quote"])
    message = ("; ".join(warnings) if warnings
               else "all required languages met")
    quote = quotes[0] if quotes else wanted[0]["quote"]
    return RuleResult("languages", True, message, quote), warnings


def check(req: dict, posting: Posting, master: dict, company: dict | None, rates: Rates | None,
          today: date, *, clt_factor: float) -> Verdict:
    """Apply the four rules in order. Languages only ever warn."""
    languages, warnings = _languages(req, master)
    results = [
        _years(req, master, today),
        _location(req, company),
        _salary(req, master, rates, clt_factor),
        languages,
    ]
    return Verdict(all(r.ok for r in results), results, warnings)

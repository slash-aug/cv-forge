"""Eligibility rules applied to a validated requirements.yaml (spec 7.3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from cvforge.apply.experience import engineering_months, years_limit
from cvforge.apply.ie_permits import PermitTable, load_permit_table
from cvforge.apply.ireland import permit_rule
from cvforge.apply.posting import Posting
from cvforge.apply.requirements import normalise_quote, posting_text
from cvforge.apply.requirements import quotes as requirement_quotes
from cvforge.money.normalise import Money, annual, monthly, pj_equivalent
from cvforge.money.rates import MoneyError, NoRate, Rates
from cvforge.profile.prefs import home_codes, pay_floor
from cvforge.text import fold_accents

REGIONS = {
    "brazil": ("br", "brazil", "brasil"),
    "portugal": ("pt", "portugal"),
    "ireland": ("ie", "ireland", "republic of ireland", "dublin", "cork", "galway", "limerick",
                "waterford"),
    "eu": ("eu", "eea", "european union", "emea"),
    "latam": ("latam", "latin america", "south america", "americas", "south and central america"),
    "worldwide": ("worldwide", "anywhere", "global", "remote (global)", "international"),
}
TOKEN_REGION = {token: region for region, tokens in REGIONS.items() for token in tokens}
CODE_REGION = {"BR": "brazil", "PT": "portugal", "IE": "ireland"}
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


# Posting caveats: terms matched after folding case and accents, as word prefixes.
CAVEAT_TERMS = (
    "reside", "residen", "eligib", "overlap", "travel", "time zone", "timezone",
    "work authori", "right to work", "citizen", "contractor", "employer of record", "eor",
    "resid", "elegib", "elegiv", "fuso", "sobrepos", "viage", "cidadan", "autoriza", "pj", "clt",
    "stamp", "sponsor", "permit", "eea", "authoris", "ielts")


def _term_pattern(term: str) -> str:
    body = r"\s+".join(map(re.escape, term.split()))
    return body + r"(?![0-9a-z])" if len(term) <= 3 else body  # eor, pj, clt: whole words only


CAVEAT_RE = re.compile(
    r"(?<![0-9a-z])(?:" + "|".join(_term_pattern(t) for t in CAVEAT_TERMS) + ")")
SENTENCE_BREAK = re.compile(r"[.!?\n]+")
HIRING_CONTRACT = {"eor": "clt", "contractor": "pj"}


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
    caveats: dict = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    ireland: dict | None = None


def _fold(text: str) -> str:
    return " ".join(fold_accents(text).split())


def region_class(token: str) -> str:
    return TOKEN_REGION.get(_fold(token), "other")


def home_regions(master: dict) -> set[str]:
    """Regions of the countries where the candidate can work freely, from the profile."""
    return {CODE_REGION[c] for c in home_codes(master) if c in CODE_REGION}


def home_named(quote: str | None, home: set[str]) -> set[str]:
    """Home regions named in a quote ("must reside in Brazil" names his own country)."""
    tokens = sorted((t for r in home for t in REGIONS[r]), key=len, reverse=True)
    if not tokens:
        return set()
    word = re.compile(r"\b(" + "|".join(map(re.escape, tokens)) + r")\b")
    return {region_class(w) for w in word.findall(_fold(quote or ""))} & home


def is_irish_job(req: dict) -> bool:
    loc = req["location"]
    if any(region_class(t) == "ireland" for t in loc.get("job_countries") or []):
        return True
    allowed = loc.get("allowed") or []
    return (loc["workplace"] == "remote" and bool(allowed)
            and all(region_class(t) == "ireland" for t in allowed))


def _home_names(home: set[str]) -> str:
    return " or ".join(sorted(h.title() for h in home))


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


def _location(req: dict, company: dict | None, home: set[str]) -> RuleResult:
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
        named = home_named(sponsorship.get("quote"), home)
        if not named:
            return result(False, "sponsorship or right to work refused", sponsorship.get("quote"))
        return result(True, f"{workplace} job requiring residence or work rights in "
                            f"{_home_names(named)}",
                      sponsorship.get("quote"))
    if countries & home or (remote and allowed & home):
        return result(True, f"{workplace} job in {_home_names(home)}")
    if remote and allowed & OPEN:
        return result(True, "remote, open to Latin America or worldwide")
    if sponsorship["status"] == "offered":
        return result(True, "relocation or visa support offered", sponsorship.get("quote"))
    if remote and allowed:
        return result(False, f"remote limited to {', '.join(loc['allowed'])}")
    if remote:
        # No region stated usually means no work visa is needed, so it is worth applying.
        return result(True, "remote with no region stated")
    where = f"{workplace} abroad"
    if company and company.get("sponsor"):
        types = ", ".join(s["type"] for s in company["sponsor"])
        return result(True, f"{where}; {company['name']} has a sponsor mark ({types})")
    return result(False, f"{where}, no sponsorship stated and no sponsor mark")


# Rule 3: salary


def _market(req: dict) -> str | None:
    """Pay floor market of a job: IE for Irish jobs, else its first home-country code."""
    if is_irish_job(req):
        return "IE"
    region_code = {region: code for code, region in CODE_REGION.items()}
    regions = (region_class(t) for t in req["location"].get("job_countries") or [])
    return next((region_code[r] for r in regions if r in region_code), None)


def _salary(req: dict, master: dict, rates: Rates | None,
            clt_factor: float) -> tuple[RuleResult, list[str]]:
    salary = req.get("salary") or {}
    amount = salary.get("max") if salary.get("max") is not None else salary.get("min")
    if amount is None:
        return RuleResult("salary", True, "no salary stated", None), []
    market = _market(req)
    floor = pay_floor(master, market)
    if not floor:
        if market == "IE":
            return RuleResult("salary", True, "no personal floor for Ireland; permit floors "
                                              "checked by the permit rule", salary.get("quote")), []
        return RuleResult("salary", True, "no pay floor set", salary.get("quote")), []
    which = "max" if salary.get("max") is not None else "min"
    stated = f"{which} {amount:g} {salary['currency'].upper()}/{salary['period']}"
    if market == "IE" and floor["currency"].upper() == "EUR" and floor["period"] == "year":
        return _salary_eur_year(salary, amount, stated, floor, rates)
    if rates is None:
        raise MoneyError("currency rates are needed for the salary rule")
    contract = (salary.get("contract") or "unknown").lower()
    if contract == "unknown":  # an Employer of Record in Brazil hires through CLT
        contract = HIRING_CONTRACT.get((req.get("hiring_model") or {}).get("type"), contract)
    try:
        offered = pj_equivalent(
            monthly(Money(amount, salary["currency"].upper(), salary["period"]), "BRL", rates),
            contract, clt_factor)
        floor_brl = monthly(Money(floor["amount"], floor["currency"].upper(), floor["period"]),
                            "BRL", rates)
    except NoRate as exc:  # cannot compare, so never a skip; the candidate judges the figure
        warning = f"no exchange rate for {exc.currency}: salary not checked against the pay floor"
        return RuleResult("salary", True, f"{stated}: {exc}", salary.get("quote")), [warning]
    basis = f" ({contract.upper()} x {clt_factor:g})" if contract == "clt" else ""
    message = (f"{stated}{basis} is "
               f"{offered:,.0f} BRL/month against a floor of {floor_brl:,.0f} BRL/month")
    return RuleResult("salary", offered >= floor_brl, message, salary.get("quote")), []


def _salary_eur_year(salary: dict, amount: float, stated: str, floor: dict,
                     rates: Rates | None) -> tuple[RuleResult, list[str]]:
    """An Irish job against a EUR/year floor: compared in EUR/year, no CLT basis."""
    money = Money(amount, salary["currency"].upper(), salary["period"])
    if money.currency == "EUR" and money.period == "year":
        offered = float(amount)
    else:
        try:
            if rates is None:
                raise NoRate(money.currency)
            offered = annual(money, "EUR", rates)
        except NoRate as exc:
            warning = (f"no exchange rate for {exc.currency}: "
                       "salary not checked against the pay floor")
            return RuleResult("salary", True, f"{stated}: {exc}", salary.get("quote")), [warning]
    message = (f"{stated} is {offered:,.0f} EUR/year against a floor of "
               f"{floor['amount']:,.0f} EUR/year")
    return RuleResult("salary", offered >= floor["amount"], message, salary.get("quote")), []


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


def caveat_sentences(posting_text: str) -> list[str]:
    """Every sentence with a caveat term, in posting order, without duplicates."""
    found: dict[str, None] = {}
    for raw in SENTENCE_BREAK.split(posting_text):
        sentence = raw.strip()
        if sentence and CAVEAT_RE.search(_fold(sentence)):
            found.setdefault(sentence)
    return list(found)


def uncaptured_caveats(req: dict, posting_text: str) -> list[str]:
    """Caveat sentences that no quote in requirements.yaml overlaps."""
    quotes = [normalise_quote(q) for _, q in requirement_quotes(req) if q]
    quotes = [q for q in quotes if q]
    missed = []
    for sentence in caveat_sentences(posting_text):
        norm = normalise_quote(sentence)
        if norm and not any(q in norm or norm in q for q in quotes):
            missed.append(sentence)
    return missed


def _caveats(req: dict, text: str) -> dict:
    return {"hiring_model": req.get("hiring_model"), "timezone": req.get("timezone"),
            "travel": req.get("travel"), "uncaptured": uncaptured_caveats(req, text)}


def check(req: dict, posting: Posting, master: dict, company: dict | None, rates: Rates | None,
          today: date, *, clt_factor: float, record: tuple[int, int] | None = None,
          table: PermitTable | None = None, dete_imported: bool = True) -> Verdict:
    """Apply the four rules in order. Languages only ever warn.

    An Irish job (not a home country for the candidate) gets the permit rule in place of
    the location rule.
    """
    home = home_regions(master)
    risks: list[str] = []
    ireland = None
    permit_warnings: list[str] = []
    if is_irish_job(req) and "ireland" not in home:
        table_warnings: list[str] = []
        if table is None:
            table, table_warnings = load_permit_table(today)
        place, risks, permit_warnings, ireland = permit_rule(
            req, master, record, rates, table, dete_imported=dete_imported)
        permit_warnings = permit_warnings + table_warnings
    else:
        place = _location(req, company, home)
    salary, salary_warnings = _salary(req, master, rates, clt_factor)
    languages, warnings = _languages(req, master)
    results = [_years(req, master, today), place, salary, languages]
    return Verdict(all(r.ok for r in results), results,
                   permit_warnings + salary_warnings + warnings,
                   _caveats(req, posting_text(posting)), risks, ireland)

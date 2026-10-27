"""Irish employment permit rule (CSEP, GEP) for `cvforge check`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from cvforge.apply.ie_permits import PermitTable
from cvforge.money.normalise import Money, annual
from cvforge.money.rates import NoRate, Rates
from cvforge.profile.prefs import degree_recognised

if TYPE_CHECKING:
    from cvforge.apply.check import RuleResult

SKIP_RIGHTS = {"required-without-sponsorship", "eu-only"}


def salary_eur_year(req: dict, rates: Rates | None) -> tuple[float | None, str | None]:
    """(EUR/year, None), or (None, currency) when the figure could not be converted.

    The max when stated, else the min, as the salary rule does. (None, None): no salary.
    """
    salary = req.get("salary") or {}
    amount = salary.get("max") if salary.get("max") is not None else salary.get("min")
    if amount is None:
        return None, None
    currency, period = salary["currency"].upper(), salary["period"]
    if currency == "EUR" and period == "year":
        return float(amount), None
    if rates is None:
        return None, currency
    try:
        return annual(Money(amount, currency, period), "EUR", rates), None
    except NoRate:
        return None, currency


def route_for(salary_eur_year: float | None, soc: str | None, degree: str,
              table: PermitTable) -> str:
    """The permit route a salary and occupation lead to: csep, csep-if-degree, gep or unknown."""
    if salary_eur_year is None:
        return "unknown"
    if salary_eur_year >= table.csep_any and soc not in table.ineligible_soc:
        return "csep"
    if soc in table.csol_soc and salary_eur_year >= table.csep_csol_degree:
        return {"yes": "csep", "no": "gep"}.get(degree, "csep-if-degree")
    return "gep"


def _first_text(value) -> str | None:
    if isinstance(value, dict):
        return value.get("en") or next(iter(value.values()), None)
    return value


def _english_warning(tests: list[str], master: dict) -> str:
    asked = " or ".join(t for t in tests if t != "other")
    cert = next((_first_text(c.get("name")) for c in master.get("certificates") or []
                 if "EF SET" in (_first_text(c.get("name")) or "")), None)
    return f"asks for {asked}; you hold {cert} (not a substitute)" if cert else f"asks for {asked}"


def _degree_warning(master: dict) -> str:
    study = next((_first_text(e.get("studyType")) for e in master.get("education") or []
                  if e.get("studyType")), None)
    return f"strict degree requirement; {study or 'your degree'} may not satisfy it"


def permit_rule(req: dict, master: dict, record: tuple[int, int] | None, rates: Rates | None,
                table: PermitTable, *, dete_imported: bool = True
                ) -> tuple[RuleResult, list[str], list[str], dict]:
    """The permit rule for an Irish job: (result, risks, warnings, ireland block)."""
    from cvforge.apply.check import RuleResult

    auth = req.get("work_authorisation") or {}
    sponsorship = req.get("sponsorship") or {}
    contract = req.get("contract") or {}
    soc = (req.get("occupation_soc") or {}).get("code")
    on_csol = soc in table.csol_soc
    s, unconverted = salary_eur_year(req, rates)
    sponsorship_silent = (sponsorship.get("status") == "silent"
                          and auth.get("status", "silent") == "silent")
    block = {"route": "unknown", "soc": soc, "on_csol": on_csol, "salary_eur_year": s,
             "permit_record": list(record) if record else None, "lmnt": False,
             "sponsorship_silent": sponsorship_silent}

    def skip(message: str, quote: str | None):
        return RuleResult("permit", False, message, quote), [], [], block

    if auth.get("status") in SKIP_RIGHTS:
        return skip("needs Irish/EU work rights without sponsorship", auth.get("quote"))
    if sponsorship.get("status") == "refused":
        return skip("needs Irish/EU work rights without sponsorship", sponsorship.get("quote"))
    kind, months = contract.get("type"), contract.get("months")
    if kind == "contractor" and (req.get("hiring_model") or {}).get("type") != "eor":
        return skip("contractor role; no Irish employer to hold a permit", contract.get("quote"))
    if kind == "fixed-term" and months is not None and months < table.gep_min_months:
        return skip(f"fixed term under {table.gep_min_months} months", contract.get("quote"))
    if s is not None and s < table.gep:
        return skip(f"salary {s:,.0f} below the GEP floor {table.gep:,}",
                    (req.get("salary") or {}).get("quote"))

    risks: list[str] = []
    warnings: list[str] = []
    degree = degree_recognised(master)
    route = route_for(s, soc, degree, table)
    lmnt_suffix = "" if on_csol else "; needs a labour market test"
    short_term = (kind == "fixed-term" and months is not None
                  and table.gep_min_months <= months < table.csep_min_months)
    if route == "unknown":
        risks.append(f"salary in {unconverted} could not be converted; not compared"
                     if unconverted else
                     f"salary unknown; CSEP needs {table.csep_csol_degree:,} with a recognised "
                     f"degree or {table.csep_any:,}")
    if short_term:
        route = "gep"
        risks.append(f"fixed term under {table.csep_min_months // 12} years: GEP only{lmnt_suffix}")
    elif route == "csep-if-degree":
        risks.append("CSEP only if the Tecnólogo is recognised as a relevant degree; otherwise "
                     "GEP (no labour market test for a CSOL occupation)")
    elif route == "gep":
        risks.append("GEP only" + lmnt_suffix)
    block["route"] = route
    block["lmnt"] = route == "gep" and not on_csol

    if sponsorship_silent and record is None:
        risks.append("no sponsorship stated and no permit record"
                     + ("" if dete_imported else " (DETE data not imported)"))
    tests = (req.get("english_test") or {}).get("tests") or []
    if any(t != "other" for t in tests):
        warnings.append(_english_warning(tests, master))
    if (req.get("degree") or {}).get("requirement") == "required":
        warnings.append(_degree_warning(master))
    if soc is None:
        warnings.append("no SOC code recorded; CSOL status unknown")

    message = f"Irish job; permit route {route}"
    if record:
        message += f"; has sponsored {record[1]} permits in {record[0]}"
    quote = auth.get("quote") or sponsorship.get("quote") or (req.get("location") or {}).get("quote")
    return RuleResult("permit", True, message, quote), risks, warnings, block

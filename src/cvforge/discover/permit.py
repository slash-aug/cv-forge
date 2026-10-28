"""The Irish employment-permit salary check for a discovered role."""
from __future__ import annotations

from dataclasses import dataclass

from cvforge.apply.ie_permits import PermitTable
from cvforge.apply.ireland import route_for, salary_eur_year, salary_min_eur_year
from cvforge.money.rates import Rates
from cvforge.profile.prefs import degree_recognised, work_rights

PERIODS = ("year", "month", "hour")


@dataclass(frozen=True)
class PermitOutcome:
    drop: bool
    route: str  # csep | csep-if-degree | gep | unknown
    salary_unknown: bool
    eur_min: float | None
    eur_max: float | None


def _unknown() -> PermitOutcome:
    return PermitOutcome(False, "unknown", True, None, None)


def _clean(salary: dict | None) -> dict | None:
    """The salary with a known lowercase period and a string currency, else None."""
    if not isinstance(salary, dict):
        return None
    period = salary.get("period")
    currency = salary.get("currency")
    if not isinstance(period, str) or period.strip().lower() not in PERIODS:
        return None
    if not isinstance(currency, str) or not currency.strip():
        return None
    return {**salary, "period": period.strip().lower(), "currency": currency.strip(),
            "min": _positive(salary.get("min")), "max": _positive(salary.get("max"))}


def _positive(amount):
    """None for a zero or negative amount; a non-numeric one is left for the caller to reject."""
    try:
        return None if float(amount) <= 0 else amount
    except (TypeError, ValueError):
        return amount


def needs_rates(salary: dict | None) -> bool:
    """True for a salary that is not already EUR per year."""
    clean = _clean(salary)
    if clean is None:
        return False
    return not (clean["currency"].upper() == "EUR" and clean["period"] == "year")


def permit_outcome(salary: dict | None, master: dict, table: PermitTable,
                   rates: Rates | None) -> PermitOutcome:
    clean = _clean(salary)
    if clean is None or (clean.get("min") is None and clean.get("max") is None):
        return _unknown()
    req = {"salary": clean}
    try:
        eur_max, _ = salary_eur_year(req, rates)
        eur_min = salary_min_eur_year(req, rates)
    except (ValueError, TypeError, ArithmeticError):
        return _unknown()
    if eur_max is None:
        return _unknown()
    soc_codes = (work_rights(master, "IE") or {}).get("soc") or []
    soc = soc_codes[0] if soc_codes else None
    # A feed may swap min and max: the route uses the lower figure, the drop gate the higher.
    figures = [f for f in (eur_min, eur_max) if f is not None]
    low, high = min(figures), max(figures)
    route = route_for(low, soc, degree_recognised(master), table)
    return PermitOutcome(high < table.gep, route, False, low, high)

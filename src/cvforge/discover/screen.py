"""Screen a discovered role in the spec order and stop at the first drop."""
from __future__ import annotations

from dataclasses import dataclass, field

from cvforge.apply.ie_permits import PermitTable
from cvforge.discover.filters import (
    is_senior,
    is_software,
    market_of,
    refuses_sponsorship,
    stack_fit,
)
from cvforge.discover.permit import PermitOutcome, permit_outcome
from cvforge.discover.sources import Role
from cvforge.money.rates import Rates

DROP_REASONS = ("out-of-market", "not-software", "senior", "no-sponsorship", "misaligned",
                "below-permit")


@dataclass
class Outcome:
    market: str | None
    drop: str | None  # one of DROP_REASONS, or None when shown
    fit: str | None  # match | partial | misaligned
    matched: list[str] = field(default_factory=list)
    route: str | None = None  # Irish roles only
    salary: PermitOutcome | None = None
    tags: list[str] = field(default_factory=list)


def screen(role: Role, *, home: str, keywords: list[str], master: dict,
           table: PermitTable, rates: Rates | None) -> Outcome:
    market, region_unknown = market_of(role.location, role.workplace, role.description, home)
    if market is None:
        return Outcome(market=None, drop="out-of-market", fit=None)
    if not is_software(role.title):
        return Outcome(market=market, drop="not-software", fit=None)
    if is_senior(role.title, role.description):
        return Outcome(market=market, drop="senior", fit=None)
    text = f"{role.title}\n{role.description}"
    if market == "IE" and refuses_sponsorship(text):
        return Outcome(market=market, drop="no-sponsorship", fit=None)
    fit, matched = stack_fit(text, keywords)
    if fit == "misaligned":
        return Outcome(market=market, drop="misaligned", fit=fit, matched=matched)
    tags: list[str] = []
    if region_unknown:
        tags.append("region unknown")
    if fit == "partial":
        tags.append("partial")
    route = salary = None
    if market == "IE":
        salary = permit_outcome(role.salary, master, table, rates)
        if salary.drop:
            return Outcome(market=market, drop="below-permit", fit=fit, matched=matched,
                           route=salary.route, salary=salary, tags=tags)
        route = salary.route
        if salary.salary_unknown:
            tags.append("salary unknown")
    return Outcome(market=market, drop=None, fit=fit, matched=matched, route=route, salary=salary, tags=tags)

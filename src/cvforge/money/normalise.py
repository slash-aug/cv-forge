"""Salary normalisation across currencies, periods and Brazilian contract basis.

CLT vs PJ: a CLT employee is paid 13 salaries plus a third of a month's
vacation pay, and the employer adds FGTS at 8%. That is about 1.2 times the
monthly salary. Health, meal and transport benefits push the usual market rule
to 1.4, which is the default factor. It is configurable (`clt_factor`).
"""
from __future__ import annotations

from dataclasses import dataclass

from cvforge.money.rates import Rates, convert

HOURS_PER_MONTH = 168
MONTHS_PER_YEAR = 12


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str
    period: str  # hour | month | year


def monthly(m: Money, currency: str, rates: Rates) -> float:
    if m.period == "month":
        per_month = m.amount
    elif m.period == "year":
        per_month = m.amount / MONTHS_PER_YEAR
    elif m.period == "hour":
        per_month = m.amount * HOURS_PER_MONTH
    else:
        raise ValueError(f"unknown period: {m.period!r}")
    return convert(per_month, m.currency, currency, rates)


def annual(m: Money, currency: str, rates: Rates) -> float:
    return monthly(m, currency, rates) * MONTHS_PER_YEAR


def pj_equivalent(monthly_amount: float, contract: str, clt_factor: float) -> float:
    return monthly_amount * clt_factor if contract == "clt" else monthly_amount

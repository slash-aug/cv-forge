"""Salary normalisation across currencies, periods and Brazilian contract basis.

CLT vs PJ: a CLT employee is paid 13 salaries plus a third of a month's
vacation pay, and the employer adds FGTS at 8%. That is about 1.2 times the
monthly salary. Health, meal and transport benefits push the usual market rule
to 1.4, which is the default factor. It is configurable (`clt_factor`).
"""
from __future__ import annotations

from dataclasses import dataclass

from cvforge.money.rates import Rates, convert

MONTHS_PER_YEAR = 12
WEEKS_PER_YEAR = 52
WORKDAYS_PER_YEAR = WEEKS_PER_YEAR * 5
HOURS_PER_YEAR = WEEKS_PER_YEAR * 40   # 8-hour days, so hour, day, week, month and year agree
HOURS_PER_MONTH = HOURS_PER_YEAR / MONTHS_PER_YEAR
PERIODS = ("hour", "day", "week", "month", "year")


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


def breakdown(m: Money, currency: str, rates: Rates) -> dict[str, float]:
    """The amount in currency for every period a form may ask for."""
    per_month = monthly(m, currency, rates)
    year = per_month * MONTHS_PER_YEAR
    values = {"hour": per_month / HOURS_PER_MONTH, "day": year / WORKDAYS_PER_YEAR,
              "week": year / WEEKS_PER_YEAR, "month": per_month, "year": year}
    return {p: round(values[p], 2) for p in PERIODS}


def shown_amount(value: float, period: str) -> str:
    """An amount as a form would take it: cents for hourly rates, whole units otherwise."""
    return f"{value:,.{2 if period == 'hour' else 0}f}"


def pj_equivalent(monthly_amount: float, contract: str, clt_factor: float) -> float:
    return monthly_amount * clt_factor if contract == "clt" else monthly_amount

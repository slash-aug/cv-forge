"""Expected salary for an application form: upper-middle of the range, never below the floor.

Inputs are the posted range, market rows and the candidate's pay floor. Current
pay is not an input anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from cvforge.money.normalise import (
    HOURS_PER_MONTH,
    MONTHS_PER_YEAR,
    Money,
    annual,
    monthly,
    pj_equivalent,
)
from cvforge.money.rates import MoneyError, Rates, convert

POSITION = 0.75
ROUND_TO = {"hour": 1, "month": 100, "year": 1000}


@dataclass(frozen=True)
class Suggestion:
    basis: str  # posting | market | floor
    amount: float
    currency: str
    period: str
    brl_month: float
    eur_year: float
    usd_year: float
    sources: list[str]


def displays(amount: float, currency: str, period: str, rates: Rates) -> tuple[float, float, float]:
    m = Money(amount, currency, period)
    return monthly(m, "BRL", rates), annual(m, "EUR", rates), annual(m, "USD", rates)


def _round(value: float, period: str) -> float:
    step = ROUND_TO[period]
    return round(value / step) * step


def _num(value) -> float | None:
    return None if value in (None, "") else float(value)


def _range(posted: dict | None, market: list[dict], floor: Money | None, rates: Rates,
           market_period: str = "month"):
    """(low, high, currency, period, basis, sources, contract)"""
    if posted:
        lo, hi = _num(posted.get("min")), _num(posted.get("max"))
        if lo is not None or hi is not None:
            lo, hi = (lo if lo is not None else hi), (hi if hi is not None else lo)
            src = [posted["quote"]] if posted.get("quote") else ["posted range"]
            return (lo, hi, posted["currency"], posted["period"], "posting", src,
                    posted.get("contract") or "unknown")
    rows = [r for r in market if _num(r.get("low")) is not None and _num(r.get("high")) is not None]
    if rows:
        cur = rows[0]["currency"]
        to_period = monthly if market_period == "month" else annual
        lows = [to_period(Money(float(r["low"]), r["currency"], r["period"]), cur, rates)
                for r in rows]
        highs = [to_period(Money(float(r["high"]), r["currency"], r["period"]), cur, rates)
                 for r in rows]
        src = [f"{r['source']} {r['year']}".strip() for r in rows]
        return min(lows), max(highs), cur, market_period, "market", src, "unknown"
    if floor is None:
        raise MoneyError("no posted salary, market rows or pay floor to suggest from")
    return (floor.amount, floor.amount, floor.currency, floor.period, "floor",
            ["payFloor (candidate minimum)"], "unknown")


def suggest(posted: dict | None, market: list[dict], floor: Money | None, rates: Rates,
            *, clt_factor: float, min_eur_year: float | None = None) -> Suggestion:
    low, high, cur, period, basis, sources, contract = _range(
        posted, market, floor, rates, "year" if min_eur_year is not None else "month")
    amount = _round(low + POSITION * (high - low), period)
    factor = clt_factor if contract == "clt" else 1.0
    if floor is not None:
        floor_brl = monthly(floor, "BRL", rates)
        brl = monthly(Money(amount, cur, period), "BRL", rates)
        if pj_equivalent(brl, contract, clt_factor) < floor_brl:
            # Lift to the floor on the contract's own basis, rounding up so it stays above.
            per_month = convert(floor_brl / factor, "BRL", cur, rates)
            raw = per_month if period == "month" else monthly_to_period(per_month, period)
            amount = math.ceil(raw / ROUND_TO[period]) * ROUND_TO[period]
            sources = [*sources, "lifted to payFloor"]
    if min_eur_year is not None and annual(Money(amount, cur, period), "EUR", rates) < min_eur_year:
        per_month = convert(min_eur_year / MONTHS_PER_YEAR, "EUR", cur, rates)
        raw = monthly_to_period(per_month, period)
        amount = math.ceil(raw / ROUND_TO[period]) * ROUND_TO[period]
        sources = [*sources, f"lifted to CSEP floor {min_eur_year:,.0f}"]
    brl_m, eur_y, usd_y = displays(amount, cur, period, rates)
    return Suggestion(basis, amount, cur, period, brl_m, eur_y, usd_y, sources)


def below_floor(amount: float, currency: str, period: str, contract: str, floor: Money,
                rates: Rates, *, clt_factor: float) -> bool:
    """True when the amount, on the same basis suggest() uses, is under the floor."""
    brl = monthly(Money(amount, currency, period), "BRL", rates)
    return pj_equivalent(brl, contract, clt_factor) < monthly(floor, "BRL", rates)


def monthly_to_period(per_month: float, period: str) -> float:
    return {"month": per_month, "year": per_month * MONTHS_PER_YEAR,
            "hour": per_month / HOURS_PER_MONTH}[period]

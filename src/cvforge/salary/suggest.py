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
from cvforge.money.rates import Rates, convert

POSITION = 0.75
ROUND_TO = 100


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


def _round(value: float) -> float:
    return round(value / ROUND_TO) * ROUND_TO


def _num(value) -> float | None:
    return None if value in (None, "") else float(value)


def _range(posted: dict | None, market: list[dict], floor: Money, rates: Rates):
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
        lows = [monthly(Money(float(r["low"]), r["currency"], r["period"]), cur, rates) for r in rows]
        highs = [monthly(Money(float(r["high"]), r["currency"], r["period"]), cur, rates)
                 for r in rows]
        src = [f"{r['source']} {r['year']}".strip() for r in rows]
        return min(lows), max(highs), cur, "month", "market", src, "unknown"
    return (floor.amount, floor.amount, floor.currency, floor.period, "floor",
            ["payFloor (candidate minimum)"], "unknown")


def suggest(posted: dict | None, market: list[dict], floor: Money, rates: Rates,
            *, clt_factor: float) -> Suggestion:
    low, high, cur, period, basis, sources, contract = _range(posted, market, floor, rates)
    amount = _round(low + POSITION * (high - low))
    factor = clt_factor if contract == "clt" else 1.0
    floor_brl = monthly(floor, "BRL", rates)
    brl = monthly(Money(amount, cur, period), "BRL", rates)
    if pj_equivalent(brl, contract, clt_factor) < floor_brl:
        # Lift to the floor on the contract's own basis, rounding up so it stays above.
        per_month = convert(floor_brl / factor, "BRL", cur, rates)
        raw = per_month if period == "month" else monthly_to_period(per_month, period)
        amount = math.ceil(raw / ROUND_TO) * ROUND_TO
        sources = [*sources, "lifted to payFloor"]
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

"""ECB euro reference rates with a per-day file cache."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}"


class MoneyError(Exception):
    """Rates could not be obtained."""


class NoRate(MoneyError):
    """The ECB publishes no reference rate for this currency (ARS, CLP, COP, ...)."""

    def __init__(self, currency: str):
        super().__init__(f"no exchange rate for {currency} (the ECB does not publish it)")
        self.currency = currency


@dataclass(frozen=True)
class Rates:
    day: str
    per_eur: dict[str, float]


def parse_ecb(xml: str) -> Rates:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise MoneyError(f"invalid ECB XML: {exc}") from exc
    day_cube = next((c for c in root.iter(f"{_NS}Cube") if c.get("time")), None)
    if day_cube is None:
        raise MoneyError("ECB XML has no dated Cube")
    per_eur = {"EUR": 1.0}
    for c in day_cube.findall(f"{_NS}Cube"):
        per_eur[c.get("currency")] = float(c.get("rate"))
    return Rates(day=day_cube.get("time"), per_eur=per_eur)


def _read(path: Path) -> Rates:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Rates(day=str(data["day"]),
                     per_eur={k: float(v) for k, v in data["per_eur"].items()})
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MoneyError(f"{path}: unreadable rate cache ({exc!r}); delete it to fetch again") from exc


def load_rates(cache_dir: Path, today: date, get: Callable[..., str]) -> Rates:
    """Today's cached rates, else fetch and cache, else the newest cache (warns)."""
    cache_file = cache_dir / f"ecb-{today.isoformat()}.json"
    if cache_file.exists():
        return _read(cache_file)
    try:
        rates = parse_ecb(get(ECB_URL))
    except Exception as exc:  # FetchError or unparsable payload
        cached = sorted(cache_dir.glob("ecb-*.json")) if cache_dir.is_dir() else []
        if not cached:
            raise MoneyError(f"no ECB rates available and no cache: {exc}") from exc
        print(f"warning: ECB fetch failed ({exc}); using {cached[-1].name}", file=sys.stderr)
        return _read(cached[-1])
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"day": rates.day, "per_eur": rates.per_eur}), encoding="utf-8"
    )
    return rates


def convert(amount: float, src: str, dst: str, rates: Rates) -> float:
    try:
        return amount / rates.per_eur[src.upper()] * rates.per_eur[dst.upper()]
    except KeyError as exc:
        raise NoRate(exc.args[0]) from exc

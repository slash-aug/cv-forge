"""Market salary rows from a CSV the candidate maintains."""
from __future__ import annotations

import csv
import math
import unicodedata
from pathlib import Path

from cvforge.profile.model import ProfileError

MARKET_COLUMNS = ("role", "seniority", "country", "currency", "period",
                  "low", "mid", "high", "source", "year")


class MarketError(ProfileError):
    pass


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in plain if not unicodedata.combining(c))


def load_market(path: Path) -> list[dict]:
    """Validated rows of the market CSV; a missing file means no rows."""
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in MARKET_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise MarketError(f"{path}: missing columns: {', '.join(missing)}")
        rows = []
        for n, raw in enumerate(reader, start=2):
            r = {k: (v or "").strip() for k, v in raw.items() if k is not None}
            for col in ("low", "mid", "high"):
                if r[col] == "" and col == "mid":
                    continue
                try:
                    ok = math.isfinite(float(r[col])) and float(r[col]) >= 0
                except ValueError:
                    ok = False
                if not ok:
                    raise MarketError(f"{path}: row {n}: {col} is not a number: {r[col]!r}")
            rows.append(r)
    return rows


def match_market(rows: list[dict], *, role: str, seniority: str, country: str) -> list[dict]:
    """Rows for the job country whose role words all appear in the posting title (`role`).

    A row's seniority matches when it is `any` or equals the posting's.
    """
    title_words = set(_fold(role).split())
    out = []
    for r in rows:
        words = _fold(r.get("role", "")).split()
        if (r.get("country", "").upper() == country.upper()
                and r.get("seniority", "any") in ("any", seniority)
                and words and all(w in title_words for w in words)):
            out.append(r)
    return out

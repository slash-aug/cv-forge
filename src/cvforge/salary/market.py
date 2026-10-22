"""Market salary rows from a CSV the candidate maintains."""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path

MARKET_COLUMNS = ("role", "seniority", "country", "currency", "period",
                  "low", "mid", "high", "source", "year")


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in plain if not unicodedata.combining(c))


def load_market(path: Path) -> list[dict]:
    """Rows of the market CSV; a missing file means no rows."""
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


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

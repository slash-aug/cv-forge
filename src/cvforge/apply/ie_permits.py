"""Dated Irish employment permit thresholds (CSEP, GEP)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import resources

import yaml

STALE_AFTER_DAYS = 365


@dataclass(frozen=True)
class PermitTable:
    effective_from: date
    csep_csol_degree: int
    csep_any: int
    gep: int
    csep_min_months: int
    gep_min_months: int
    csol_soc: frozenset[str]
    ineligible_soc: frozenset[str]
    source: str


def _parse(entry: dict) -> PermitTable:
    return PermitTable(
        effective_from=entry["effective_from"],
        csep_csol_degree=int(entry["csep_csol_degree"]),
        csep_any=int(entry["csep_any"]),
        gep=int(entry["gep"]),
        csep_min_months=int(entry["csep_min_months"]),
        gep_min_months=int(entry["gep_min_months"]),
        csol_soc=frozenset(str(c) for c in entry["csol_soc"]),
        ineligible_soc=frozenset(str(c) for c in entry["ineligible_soc"]),
        source=str(entry["source"]),
    )


def _tables() -> list[PermitTable]:
    text = resources.files("cvforge.apply").joinpath("ie_permits.yaml").read_text(encoding="utf-8")
    return sorted((_parse(e) for e in yaml.safe_load(text)["tables"]), key=lambda t: t.effective_from)


def load_permit_table(today: date) -> tuple[PermitTable, list[str]]:
    """Return the table in force on `today` and any warnings about it."""
    tables = _tables()
    in_force = [t for t in tables if t.effective_from <= today]
    if not in_force:
        raise ValueError(f"no Irish permit thresholds in force on {today.isoformat()}")
    table = in_force[-1]
    warnings: list[str] = []
    newest = tables[-1]
    if (today - newest.effective_from).days > STALE_AFTER_DAYS:
        warnings.append(
            f"Irish permit thresholds last updated {newest.effective_from.isoformat()}; "
            "check enterprise.gov.ie for newer figures"
        )
    return table, warnings

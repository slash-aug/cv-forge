"""Data a screening answer may be grounded in beyond the master's highlights."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cvforge.answers.facts import knockout_facts
from cvforge.apply.experience import engineering_months
from cvforge.tailor.audit import figures


class DataError(Exception):
    """A file under the data directory that cannot be used as it is."""


SALARY_KEYS = ("amount", "currency", "period", "brl_month", "eur_year", "usd_year")


def load_salary(app_dir: Path) -> dict | None:
    """salary.json as written by `cvforge salary`, or None; a damaged file is a DataError."""
    path = app_dir / "salary.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DataError(f"{path}: unreadable ({exc}); rerun cvforge salary") from None
    if not isinstance(data, dict):
        raise DataError(f"{path}: expected an object; rerun cvforge salary")
    if data.get("confirmed"):
        missing = [k for k in SALARY_KEYS if k not in data]
        if missing:
            raise DataError(f"{path}: missing {', '.join(missing)}; rerun cvforge salary")
        try:
            for key in ("amount", "brl_month", "eur_year", "usd_year"):
                data[key] = float(data[key])
        except (TypeError, ValueError):
            raise DataError(f"{path}: {key} is not a number; rerun cvforge salary") from None
    return data


def answer_figures(master: dict, lang: str, app_dir: Path, today: date) -> set[str]:
    """Numbers an honest screening answer may hold that no highlight has: the knock-out facts
    (years from dates, notice) and, once confirmed, the salary as `cvforge salary` shows it."""
    facts = knockout_facts(master, engineering_months(master, today), lang)
    found = figures(*facts.values())
    salary = load_salary(app_dir)
    if salary and salary.get("confirmed"):
        amount = salary["amount"]
        found |= figures(f"{amount:g}", f"{amount:.0f}", f"{amount:,.0f}", f"{amount:,.2f}")
        for key in ("brl_month", "eur_year", "usd_year"):
            found |= figures(f"{salary[key]:.0f}", f"{salary[key]:,.0f}")
    return found

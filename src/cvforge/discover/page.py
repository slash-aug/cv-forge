"""Render a discovery run to one self-contained HTML page opened from disk."""
from __future__ import annotations

from datetime import datetime

from cvforge.discover.rows import Row, intake_command, is_tagged
from cvforge.discover.run import RunResult
from cvforge.discover.screen import DROP_REASONS
from cvforge.discover.store import is_new
from cvforge.kit.render import make_env

MARKETS = (("IE", "Ireland"), ("BR", "Brazil"))
ROUTES = {
    "csep": "CSEP",
    "csep-if-degree": "CSEP only if the degree is recognised, else GEP",
    "gep": "GEP",
}


def route_label(route: str | None) -> str:
    return ROUTES.get(route or "", "route unknown")


def _amount(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{value:,.0f}"


def salary_text(salary: dict | None) -> str:
    if not salary:
        return "salary unknown"
    low, high = _amount(salary.get("min")), _amount(salary.get("max"))
    bounds = "-".join(dict.fromkeys(b for b in (low, high) if b))
    if not bounds:
        return "salary unknown"
    amount = " ".join(x for x in (bounds, salary.get("currency")) if x)
    return " / ".join(x for x in (amount, salary.get("period")) if x)


def _view(row: Row, last_viewed: datetime | None) -> dict:
    return {"row": row, "new": is_new(row.first_seen, row.applied, last_viewed), "tagged": is_tagged(row),
            "salary": salary_text(row.salary),
            # Brazil needs no permit, so its cards carry no route label.
            "route": route_label(row.route) if row.market == "IE" else None,
            "first_seen": (row.first_seen or "")[:10]}


def render_jobs(result: RunResult, last_viewed: datetime | None) -> str:
    env = make_env("cvforge.discover")
    env.globals["intake_command"] = intake_command
    sections = []
    for code, label in MARKETS:
        views = [_view(r, last_viewed) for r in result.rows if r.market == code]
        sections.append({"label": label, "open": [v for v in views if v["row"].applied is None],
                         "applied": [v for v in views if v["row"].applied is not None]})
    dropped = [(reason, result.dropped.get(reason, 0)) for reason in DROP_REASONS]
    return env.get_template("jobs.html.j2").render(
        day=result.now.date().isoformat(), sections=sections, dropped=dropped,
        errors=result.errors, manual=result.manual)

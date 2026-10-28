"""Render a discovery run to one self-contained HTML page opened from disk."""
from __future__ import annotations

from datetime import datetime
from importlib import resources

import jinja2

from cvforge.discover.rows import Row, intake_command, is_tagged
from cvforge.discover.run import RunResult
from cvforge.discover.screen import DROP_REASONS
from cvforge.kit.render import is_web

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


def _is_new(row: Row, last_viewed: datetime | None) -> bool:
    if row.applied is not None:
        return False
    if last_viewed is None:
        return True
    try:
        seen = datetime.fromisoformat(row.first_seen)
    except (TypeError, ValueError):
        return True  # an odd stamp: show it rather than hide it
    if seen.tzinfo is None and last_viewed.tzinfo is not None:
        seen = seen.replace(tzinfo=last_viewed.tzinfo)
    elif seen.tzinfo is not None and last_viewed.tzinfo is None:
        last_viewed = last_viewed.replace(tzinfo=seen.tzinfo)
    return seen > last_viewed


def _view(row: Row, last_viewed: datetime | None) -> dict:
    return {"row": row, "new": _is_new(row, last_viewed), "tagged": is_tagged(row),
            "salary": salary_text(row.salary),
            # Brazil needs no permit, so its cards carry no route label.
            "route": route_label(row.route) if row.market == "IE" else None,
            "first_seen": (row.first_seen or "")[:10]}


def render_jobs(result: RunResult, last_viewed: datetime | None) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(resources.files("cvforge.discover").joinpath("templates"))),
        autoescape=True, trim_blocks=True, lstrip_blocks=True, undefined=jinja2.StrictUndefined)
    env.tests["web"] = is_web
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

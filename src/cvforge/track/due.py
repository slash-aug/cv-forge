"""What needs attention today: stages, follow-ups and stale applications."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from cvforge.track.stages import Stage, StagesError, load_stages
from cvforge.track.tracker import FINAL


@dataclass
class DueReport:
    stages: list[tuple[str, Stage]]
    followups: list[dict]
    stale: list[dict]
    errors: list[str] = field(default_factory=list)


def _age(row: dict, today: date) -> int | None:
    stamp = row.get("last_update") or row.get("date") or ""  # legacy rows lack last_update
    try:
        return (today - date.fromisoformat(stamp)).days
    except ValueError:
        return None


def due_report(rows: list[dict], apps_dir: Path, today: date, *, window: int = 7,
               followup: int = 10, stale: int = 60) -> DueReport:
    horizon = today + timedelta(days=window)
    stages, errors = [], []
    for r in rows:
        if r["status"] in FINAL:  # closed applications have no stages left to attend
            continue
        try:
            found = load_stages(Path(apps_dir) / r["slug"])
        except StagesError as exc:
            errors.append(f"{r['slug']}: {exc}")
            continue
        stages += [(r["slug"], s) for s in found if not s.done and s.due is not None and s.due <= horizon]
    stages.sort(key=lambda item: item[1].due)
    follow, old = [], []
    for row in rows:
        status = row["status"]
        age = _age(row, today)
        if age is None or status in FINAL or status == "drafted":
            continue
        if age >= stale:
            old.append(row)
        elif age >= followup and status in ("applied", "assessment"):
            follow.append(row)
    return DueReport(stages=stages, followups=follow, stale=old, errors=errors)

"""What needs attention today: stages, follow-ups and stale applications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from cvforge.track.stages import Stage, load_stages
from cvforge.track.tracker import FINAL


@dataclass
class DueReport:
    stages: list[tuple[str, Stage]]
    followups: list[dict]
    stale: list[dict]


def _age(row: dict, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(row["last_update"])).days
    except (ValueError, KeyError):
        return None


def due_report(rows: list[dict], apps_dir: Path, today: date, *, window: int = 7,
               followup: int = 10, stale: int = 60) -> DueReport:
    horizon = today + timedelta(days=window)
    stages = [(r["slug"], s) for r in rows for s in load_stages(Path(apps_dir) / r["slug"])
              if not s.done and s.due is not None and s.due <= horizon]
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
    return DueReport(stages=stages, followups=follow, stale=old)

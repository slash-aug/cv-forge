"""Per-application stages (tests, interviews, cases) stored in <app_dir>/stages.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from cvforge.text import squash

KINDS = ("test", "interview", "case", "form", "other")


@dataclass
class Stage:
    name: str
    kind: str
    due: date | None = None
    done: bool = False
    notes: str = ""


def _file(app_dir: Path) -> Path:
    return Path(app_dir) / "stages.yaml"


def _due(value) -> date | None:
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def load_stages(app_dir: Path) -> list[Stage]:
    path = _file(app_dir)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Stage(name=str(s["name"]), kind=s.get("kind", "other"), due=_due(s.get("due")),
                  done=bool(s.get("done", False)), notes=s.get("notes") or "")
            for s in data.get("stages", [])]


def _save(app_dir: Path, stages: list[Stage]) -> None:
    path = _file(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stages": [{"name": s.name, "kind": s.kind,
                           "due": s.due.isoformat() if s.due else None,
                           "done": s.done, "notes": s.notes} for s in stages]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def add_stage(app_dir: Path, name: str, kind: str, due: date | None) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown stage kind '{kind}'")
    stages = load_stages(app_dir)
    stages.append(Stage(name=name, kind=kind, due=due))
    _save(app_dir, stages)


def complete_stage(app_dir: Path, name: str) -> None:
    stages = load_stages(app_dir)
    stage = next((s for s in stages if squash(s.name) == squash(name)), None)
    if stage is None:
        raise KeyError(f"no stage named '{name}'")
    stage.done = True
    _save(app_dir, stages)

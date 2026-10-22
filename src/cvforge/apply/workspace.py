"""Per-application directories under data/applications."""
from __future__ import annotations

from pathlib import Path

from cvforge.text import slug


def new_slug(apps_dir: Path, company: str, role: str) -> str:
    """company-role, with -2, -3 ... added while the directory exists."""
    base = f"{slug(company)}-{slug(role)}".strip("-") or "application"
    candidate, n = base, 1
    while (apps_dir / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def create_app_dir(apps_dir: Path, company: str, role: str) -> Path:
    path = apps_dir / new_slug(apps_dir, company, role)
    path.mkdir(parents=True)
    return path

"""Seed the company registry with Irish employers and their ATS boards."""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from cvforge.apply.companies import (
    ATS,
    CompanyError,
    _defaults,
    _save,
    find_company,
    load_registry,
)

SEED_NOTE = "seed: JobPilot ireland preset 405f706"
SEED_FILE = "seeds/ie_companies.json"
URLS = {
    "greenhouse": "https://boards.greenhouse.io/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}",
    "workable": "https://apply.workable.com/{slug}",
    "personio": "https://{slug}.jobs.personio.de",
}


@dataclass
class SeedResult:
    added: int
    kept: int


def _careers_url(item: dict) -> str:
    if item["ats"] == "workday":
        w = item["workday"]
        return f"https://{w['tenant']}.{w['wd']}.myworkdayjobs.com/{w['site']}"
    return URLS[item["ats"]].format(slug=item["slug"])


def _load_seed(seed_file: Path | None) -> list[dict]:
    if seed_file is not None:
        text = Path(seed_file).read_text(encoding="utf-8")
    else:
        text = resources.files("cvforge.apply").joinpath(SEED_FILE).read_text(encoding="utf-8")
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise CompanyError(f"seed file is not valid JSON: {exc}") from exc
    for item in items:
        if item.get("ats") not in ATS or not item.get("name"):
            raise CompanyError(f"bad seed entry: {item}")
    return items


def seed_ie(registry_path: Path, seed_file: Path | None = None) -> SeedResult:
    """Add seed employers that are not yet known; existing entries are never touched."""
    items = _load_seed(seed_file)
    registry = load_registry(registry_path)
    added = kept = 0
    for item in items:
        if find_company(registry, item["name"]) is not None:
            kept += 1
            continue
        registry.append({"name": item["name"], **_defaults(), "ats": item["ats"],
                         "careers_url": _careers_url(item), "notes": SEED_NOTE})
        added += 1
    if added:
        _save(registry_path, registry)
    return SeedResult(added, kept)

"""The application tracker: one CSV row per application, keyed by slug."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from cvforge.text import fold_accents, squash

COLUMNS: tuple[str, ...] = (
    "date", "company", "sector", "role", "role_type", "channel", "status", "contact_person",
    "fit_rating", "notes", "cv_file", "cover_letter_file", "source", "deadline",
    "slug", "url", "market", "posted_salary", "suggested_salary", "offered_salary",
    "skip_reason", "last_update",
)
STATUSES: tuple[str, ...] = (
    "drafted", "applied", "assessment", "interview", "offer", "hired", "rejected",
    "no_response", "offer_declined", "withdrawn", "skipped",
)
FINAL = frozenset({"hired", "rejected", "no_response", "offer_declined", "withdrawn", "skipped"})
CHANNELS = frozenset({"easy-apply", "external", "trainee", "platform"})
LEGACY_STATUS = {"no response": "no_response", "offer declined": "offer_declined"}
UNSAFE_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _key(text: str) -> str:
    """Case, accent and separator-insensitive form for matching names."""
    return squash(fold_accents(text))


def _today() -> date:
    return date.today()


def _safe(value: str) -> str:
    return "'" + value if value.startswith(UNSAFE_PREFIXES) else value


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [{c: (r.get(c) or "") for c in COLUMNS} for r in csv.DictReader(fh)]
    for row in rows:
        status = row["status"].strip()
        row["status"] = LEGACY_STATUS.get(status, status)
    return rows


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _safe(str(row.get(c) or "")) for c in COLUMNS})


def find(rows: list[dict], *, url: str | None = None, company: str | None = None,
         role: str | None = None) -> dict | None:
    """First row matching the url, else the folded company and role together."""
    if url:
        for row in rows:
            if row.get("url") and row["url"].strip() == url.strip():
                return row
    if company and role:
        key = (_key(company), _key(role))
        for row in rows:
            if (_key(row.get("company", "")), _key(row.get("role", ""))) == key:
                return row
    return None


def upsert(path: Path, row: dict) -> dict:
    """Insert or merge a row by slug and stamp last_update."""
    rows = load(path)
    current = next((r for r in rows if r["slug"] == row["slug"]), None)
    if current is None:
        current = {c: "" for c in COLUMNS}
        rows.append(current)
    current.update({k: v for k, v in row.items() if k in COLUMNS})
    current["last_update"] = _today().isoformat()
    save(path, rows)
    return dict(current)


def set_status(path: Path, slug: str, status: str, today: date, *, note: str = "",
               skip_reason: str = "") -> dict:
    status = LEGACY_STATUS.get(status, status)
    if status not in STATUSES:
        raise ValueError(f"unknown status '{status}'")
    rows = load(path)
    row = next((r for r in rows if r["slug"] == slug), None)
    if row is None:
        raise KeyError(f"no tracker row with slug '{slug}'")
    if status == "applied" or (row["status"] in ("", "drafted") and status != "drafted"):
        row["date"] = today.isoformat()  # "applied on", not the draft date
    row["status"] = status
    if note:
        row["notes"] = f"{row['notes']}; {note}" if row["notes"] else note
    if skip_reason:
        row["skip_reason"] = skip_reason
    row["last_update"] = today.isoformat()
    save(path, rows)
    return dict(row)


def applied_on(rows: list[dict], day: date) -> int:
    """Rows that went out on the given day (date column, any sent status)."""
    return sum(1 for r in rows
               if r["date"] == day.isoformat() and r["status"] not in ("", "drafted", "skipped"))



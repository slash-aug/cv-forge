"""What discovery has seen across runs: first sightings, removals, reposts, ghosts and run files."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from cvforge.apply.companies import name_key
from cvforge.discover.sources import Role
from cvforge.text import fold_accents

STALE_DAYS = 14
GHOST_DAYS = 90
RUN_KEEP_DAYS = 90

GENDER_MARK = re.compile(r"\(\s*[a-z]\s*/\s*[a-z](?:\s*/\s*[a-z])?\s*\)")
NON_WORD = re.compile(r"[\W_]+")
LETTERS = re.compile(r"[^\W\d_]+")
RUN_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def norm_title(title: str) -> str:
    folded = GENDER_MARK.sub(" ", fold_accents(title))
    return NON_WORD.sub(" ", folded).strip()


def fingerprint(description: str) -> str:
    words = " ".join(LETTERS.findall(fold_accents(description or "")))
    return hashlib.sha1(words.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_seen(path: Path) -> dict[str, dict]:
    return _read_json(path) or {}


def save_seen(path: Path, seen: dict[str, dict]) -> None:
    _write_json(path, seen)


def update_seen(seen: dict[str, dict], roles: list[Role], market_of_key: dict[str, str | None],
                *, now: datetime, fetched: set[tuple[str, str]]) -> None:
    stamp = _iso(now)
    current = {r.key for r in roles}
    for role in roles:
        key = role.key
        market = market_of_key.get(key)
        rec = seen.get(key)
        if rec is not None:
            rec["last_seen"] = stamp
            rec["market"] = market
            rec["location"] = role.location
            if rec.get("gone_since"):
                rec["times_reposted"] += 1
                rec["gone_since"] = None
            continue
        fp = fingerprint(role.description)
        company, title = name_key(role.company), norm_title(role.title)
        gone = [
            old for old in seen.values()
            if old.get("gone_since") and not old.get("successor") and old.get("fingerprint") == fp
            and name_key(old.get("company") or "") == company and norm_title(old.get("title") or "") == title
        ]
        first_seen, reposted = stamp, 0
        if gone:
            old = min(gone, key=lambda o: (-o["times_reposted"], o["first_seen"]))
            first_seen, reposted = old["first_seen"], old["times_reposted"] + 1
            old["successor"] = key
        seen[key] = {
            "key": key, "source": role.source, "board": role.board, "job_id": role.job_id,
            "company": role.company, "title": role.title, "url": role.url, "location": role.location,
            "market": market, "first_seen": first_seen, "last_seen": stamp, "gone_since": None,
            "times_reposted": reposted, "fingerprint": fp,
        }
    for key, rec in seen.items():
        if key in current or rec.get("gone_since"):
            continue
        if (rec["source"], rec["board"]) in fetched:
            rec["gone_since"] = stamp


def is_stale(record: dict, now: datetime) -> bool:
    first = datetime.fromisoformat(record["first_seen"])
    return (now.date() - first.date()).days > STALE_DAYS or record.get("times_reposted", 0) > 0


def load_ghosts(path: Path) -> dict[str, dict]:
    return _read_json(path) or {}


def save_ghosts(path: Path, ghosts: dict[str, dict]) -> None:
    _write_json(path, ghosts)


def flag_ghosts(ghosts: dict[str, dict], flagged: dict[str, str], today: date) -> None:
    for company, reason in flagged.items():
        ghosts[name_key(company)] = {"name": company, "last_flagged": today.isoformat(), "reason": reason}


def ghost_marked(company: str, ghosts: dict[str, dict], entry: dict | None, today: date) -> bool:
    auto = ghosts.get(name_key(company))
    flagged = date.fromisoformat(auto["last_flagged"]) if auto else None
    manual = (entry or {}).get("ghost")
    if manual:
        if manual.get("mark"):
            return True
        try:
            marked_on = date.fromisoformat(str(manual["date"]))
        except (KeyError, ValueError):
            marked_on = None
        if flagged is None or (marked_on is not None and marked_on >= flagged):
            return False
    return flagged is not None and (today - flagged).days <= GHOST_DAYS


def read_last_viewed(jobs_dir: Path) -> datetime | None:
    data = _read_json(jobs_dir / "last_viewed.json")
    return datetime.fromisoformat(data["at"]) if data else None


def write_last_viewed(jobs_dir: Path, now: datetime) -> None:
    _write_json(jobs_dir / "last_viewed.json", {"at": _iso(now)})


def write_run(jobs_dir: Path, today: date, payload: dict) -> Path:
    path = jobs_dir / "runs" / f"{today.isoformat()}.json"
    _write_json(path, payload)
    return path


def prune_runs(jobs_dir: Path, today: date, keep_days: int = RUN_KEEP_DAYS) -> int:
    runs = jobs_dir / "runs"
    if not runs.is_dir():
        return 0
    deleted = 0
    for path in runs.iterdir():
        match = RUN_FILE.match(path.name)
        if not match:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if (today - day).days > keep_days:
            path.unlink()
            deleted += 1
    return deleted


def read_last_run(jobs_dir: Path) -> dict | None:
    return _read_json(jobs_dir / "last_run.json")


def write_last_run(jobs_dir: Path, payload: dict) -> None:
    _write_json(jobs_dir / "last_run.json", payload)

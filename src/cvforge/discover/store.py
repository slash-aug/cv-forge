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
# runs/YYYY-MM-DDTHHMM.json; the older runs/YYYY-MM-DD.json name is still pruned by its date.
RUN_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T\d{4})?\.json$")


def norm_title(title: str) -> str:
    folded = GENDER_MARK.sub(" ", fold_accents(title))
    return NON_WORD.sub(" ", folded).strip()


def fingerprint(description: str) -> str:
    words = " ".join(LETTERS.findall(fold_accents(description or "")))
    return hashlib.sha1(words.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def write_text_atomic(path: Path, text: str) -> None:
    """Write through a temp file and rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_json(path: Path, data) -> None:
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))


def _read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_map(path: Path) -> dict[str, dict]:
    return _read_json(path) or {}


def _save_map(path: Path, data: dict[str, dict]) -> None:
    _write_json(path, data)


def load_seen(path: Path) -> dict[str, dict]:
    return _load_map(path)


def save_seen(path: Path, seen: dict[str, dict]) -> None:
    _save_map(path, seen)


def is_new(first_seen: str | None, applied: dict | None, viewed: datetime | None) -> bool:
    """A role not in the tracker and first seen after the last view; an odd stamp counts as new."""
    if applied is not None:
        return False
    if viewed is None:
        return True
    try:
        seen = datetime.fromisoformat(first_seen)
    except (TypeError, ValueError):
        return True  # show it rather than hide it
    if seen.tzinfo is None and viewed.tzinfo is not None:
        seen = seen.replace(tzinfo=viewed.tzinfo)
    elif seen.tzinfo is not None and viewed.tzinfo is None:
        viewed = viewed.replace(tzinfo=seen.tzinfo)
    return seen > viewed


def _repost_key(fp: str | None, company: str, title: str) -> tuple:
    return fp, name_key(company), norm_title(title)


def update_seen(seen: dict[str, dict], roles: list[Role], market_of_key: dict[str, str | None],
                *, now: datetime, fetched: set[tuple[str, str]]) -> None:
    stamp = _iso(now)
    current = {r.key for r in roles}
    # Gone records by repost key, in seen order; the loop below only ever removes candidates.
    gone_index: dict[tuple, list[dict]] = {}
    for old in seen.values():
        if old.get("gone_since") and not old.get("successor"):
            rkey = _repost_key(old.get("fingerprint"), old.get("company") or "", old.get("title") or "")
            gone_index.setdefault(rkey, []).append(old)
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
        gone = [
            old for old in gone_index.get(_repost_key(fp, role.company, role.title), [])
            if old.get("gone_since") and not old.get("successor")
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
    return _load_map(path)


def save_ghosts(path: Path, ghosts: dict[str, dict]) -> None:
    _save_map(path, ghosts)


def flag_ghosts(ghosts: dict[str, dict], flagged: dict[str, str], today: date) -> None:
    for company, reason in flagged.items():
        ghosts[name_key(company)] = {"name": company, "last_flagged": today.isoformat(), "reason": reason}


def ghost_marked(company: str, ghosts: dict[str, dict], entry: dict | None, today: date) -> bool:
    auto = ghosts.get(name_key(company))
    flagged = date.fromisoformat(auto["last_flagged"]) if auto else None
    manual = (entry or {}).get("ghost")
    if manual and manual.get("mark"):
        return True
    if flagged is None:
        return False
    if manual:
        try:
            marked_on = date.fromisoformat(str(manual["date"]))
        except (KeyError, ValueError):
            marked_on = None
        if marked_on is not None and marked_on >= flagged:
            return False  # cleared by hand after the last auto flag
    return (today - flagged).days <= GHOST_DAYS


def read_last_viewed(jobs_dir: Path) -> datetime | None:
    data = _read_json(jobs_dir / "last_viewed.json")
    return datetime.fromisoformat(data["at"]) if data else None


def write_last_viewed(jobs_dir: Path, now: datetime) -> None:
    _write_json(jobs_dir / "last_viewed.json", {"at": _iso(now)})


def write_run(jobs_dir: Path, now: datetime, payload: dict) -> Path:
    """One file per run, named by date and minute so a second run the same day keeps the first."""
    path = jobs_dir / "runs" / f"{now.strftime('%Y-%m-%dT%H%M')}.json"
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

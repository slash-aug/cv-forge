"""One discovery run: read every employer feed, screen roles, update state and write run files."""
from __future__ import annotations

import copy
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cvforge.apply.companies import FEED_ATS, MANUAL_ATS, board_slug
from cvforge.apply.ie_permits import PermitTable
from cvforge.apply.intake import Get
from cvforge.apply.seed import SEED_NOTE
from cvforge.discover import store
from cvforge.discover.filters import master_keywords
from cvforge.discover.permit import needs_rates
from cvforge.discover.rows import Row, build_rows
from cvforge.discover.screen import DROP_REASONS, Outcome, screen
from cvforge.discover.sources import Role, SourceError, fetch_board
from cvforge.money.rates import Rates
from cvforge.profile.prefs import primary_market

FETCH_SOURCES = ("greenhouse", "ashby", "lever", "workable", "gupy")
MARKETS = ("IE", "BR", "all")
GHOST_SIGNS = frozenset({"stale", "ghost history"})


@dataclass
class RunResult:
    now: datetime
    rows: list[Row]
    dropped: dict[str, int]
    errors: list[str]
    boards: int
    failed: int
    fetched: int
    manual: list[dict]

    @property
    def all_failed(self) -> bool:
        return self.boards > 0 and self.failed == self.boards


def _home(entry: dict, master: dict) -> str:
    notes = entry.get("notes") or ""
    marks = entry.get("sponsor") or []
    if SEED_NOTE in notes or any(isinstance(m, dict) and m.get("type") == "ie-permit" for m in marks):
        return "IE"
    return primary_market(master) or "IE"


def _feed_boards(registry: list[dict], source: str | None) -> list[dict]:
    if source == "gupy":
        return []  # Gupy is read by its own search, wired separately
    return [e for e in registry
            if e.get("ats") in FEED_ATS and board_slug(e) and (source is None or e.get("ats") == source)]


def _message(entry: dict, exc: Exception) -> str:
    text, name = str(exc), entry.get("name") or ""
    if name and text.startswith(f"{name}: "):
        text = text[len(name) + 2:]
    return f"{name or board_slug(entry)} ({entry.get('ats')}): {text}"


def _load_rates(rates: Callable[[], Rates | None]) -> Rates | None:
    try:
        return rates()
    except Exception:  # noqa: BLE001 - any failure loading rates means no rates this run
        return None


def _is_tagged(row: Row) -> bool:
    """True when the row carries a ghost sign: cloned, stale or ghost history."""
    return any(t.startswith("cloned") or t in GHOST_SIGNS for t in row.tags)


def _run_role(role: Role, out: Outcome) -> dict:
    return {"key": role.key, "company": role.company, "title": role.title, "location": role.location,
            "url": role.url, "market": out.market, "drop": out.drop, "fit": out.fit,
            "matched": list(out.matched), "tags": list(out.tags)}


def _last_run_row(row: Row) -> dict:
    return {"market": row.market, "company": row.company, "title": row.title, "locations": row.locations,
            "url": row.urls[0] if row.urls else "", "fit": row.fit, "tags": row.tags,
            "first_seen": row.first_seen, "tagged": _is_tagged(row), "applied": row.applied}


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run_fetch(jobs_dir: Path, *, master: dict, registry: list[dict], tracker_rows: list[dict],
              table: PermitTable, rates: Callable[[], Rates | None], get: Get, now: datetime,
              market: str = "all", source: str | None = None, dry_run: bool = False,
              pause: float = 1.0, gupy_keywords: tuple[str, ...] = (),
              render: Callable[[RunResult, datetime | None], str] | None = None) -> RunResult:
    if market not in MARKETS:
        raise ValueError(f"unknown market {market!r}; allowed: {', '.join(MARKETS)}")
    if source is not None and source not in FETCH_SOURCES:
        raise ValueError(f"unknown source {source!r}; allowed: {', '.join(FETCH_SOURCES)}")
    today = now.date()
    boards = _feed_boards(registry, source)
    manual = sorted(({"name": e.get("name"), "ats": e.get("ats"), "careers_url": e.get("careers_url")}
                     for e in registry if e.get("ats") in MANUAL_ATS), key=lambda m: m["name"] or "")

    fetched_roles: list[tuple[Role, str]] = []
    answered: set[tuple[str, str]] = set()
    errors: list[str] = []
    for i, entry in enumerate(boards):
        if i:
            time.sleep(pause)
        try:
            roles = fetch_board(entry, get=get, today=today)
        except SourceError as exc:
            errors.append(_message(entry, exc))
            continue
        answered.add((entry["ats"], board_slug(entry)))
        home = _home(entry, master)
        fetched_roles.extend((r, home) for r in roles)

    loaded = _load_rates(rates) if any(needs_rates(r.salary) for r, _ in fetched_roles) else None
    keywords = master_keywords(master)
    screened = [(r, screen(r, home=home, keywords=keywords, master=master, table=table, rates=loaded))
                for r, home in fetched_roles]
    dropped = {reason: 0 for reason in DROP_REASONS}
    for _, out in screened:
        if out.drop:
            dropped[out.drop] += 1
    kept = [(r, o) for r, o in screened if o.drop is None]

    seen_path, ghosts_path = jobs_dir / "seen.json", jobs_dir / "ghosts.json"
    seen = store.load_seen(seen_path)
    if dry_run:
        seen = copy.deepcopy(seen)
    ghosts = store.load_ghosts(ghosts_path)
    store.update_seen(seen, [r for r, _ in screened], {r.key: o.market for r, o in screened},
                      now=now, fetched=answered)
    last_viewed = store.read_last_viewed(jobs_dir)
    # Rows of every market feed ghost flags and last_run; --market only narrows the result and page.
    rows, flagged = build_rows(kept, seen, registry=registry, ghosts=ghosts, tracker_rows=tracker_rows,
                               last_viewed=last_viewed, now=now)
    shown = rows if market == "all" else [row for row in rows if row.market == market]
    result = RunResult(now=now, rows=shown, dropped=dropped, errors=errors, boards=len(boards),
                       failed=len(errors), fetched=len(screened), manual=manual)
    if dry_run:
        return result

    store.flag_ghosts(ghosts, flagged, today)
    store.save_seen(seen_path, seen)
    store.save_ghosts(ghosts_path, ghosts)
    at = now.isoformat(timespec="seconds")
    store.write_run(jobs_dir, today, {"at": at, "errors": errors, "dropped": dropped,
                                      "roles": [_run_role(r, o) for r, o in screened]})
    if result.all_failed:
        # Nothing was read: keep the previous list so a network outage does not empty it.
        last_rows = (store.read_last_run(jobs_dir) or {}).get("rows") or []
    else:
        last_rows = [_last_run_row(row) for row in rows]
    store.write_last_run(jobs_dir, {"at": at, "boards": result.boards, "failed": result.failed,
                                    "errors": errors, "dropped": dropped, "rows": last_rows})
    if render is not None and not result.all_failed:
        _write_text(jobs_dir / "latest.html", render(result, store.read_last_viewed(jobs_dir)))
    store.prune_runs(jobs_dir, today)
    return result


def due_lines(jobs_dir: Path, now: datetime) -> list[str]:
    last = store.read_last_run(jobs_dir)
    if not last:
        return ["jobs: never fetched; run cvforge jobs fetch"]
    viewed = store.read_last_viewed(jobs_dir)
    new = [r for r in last.get("rows") or []
           if r.get("applied") is None
           and (viewed is None or datetime.fromisoformat(r["first_seen"]) > viewed)]
    irish = sum(1 for r in new if r.get("market") == "IE")
    brazilian = sum(1 for r in new if r.get("market") == "BR")
    tagged = sum(1 for r in new if r.get("tagged"))
    lines = [f"jobs: {irish} new Irish roles, {brazilian} new Brazilian ({tagged} tagged)"]
    days = (now.date() - datetime.fromisoformat(last["at"]).date()).days
    if days > 2:
        lines.append(f"jobs: last run {days} days ago; run cvforge jobs fetch")
    if last.get("failed"):
        lines.append(f"jobs: {last['failed']} of {last.get('boards', 0)} sources failed in the last run")
    return lines

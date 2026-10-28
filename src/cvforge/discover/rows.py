"""Screened roles as list rows: clones and locations merged, tagged, marked applied or new."""
from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from cvforge.apply.companies import find_company, name_key
from cvforge.apply.posting import canonical_url
from cvforge.discover.screen import Outcome
from cvforge.discover.sources import Role
from cvforge.discover.store import ghost_marked, is_new, is_stale, norm_title
from cvforge.kit.render import is_web
from cvforge.text import fold_accents

CLONE_SIMILARITY = 0.8
MARKET_ORDER = {"IE": 0, "BR": 1}
WORDS = re.compile(r"\w+")
SPACE = re.compile(r"\s+")
GHOST_SIGNS = frozenset({"stale", "ghost history"})
IE_SPONSOR_TYPES = frozenset({"ie-permit", "other"})


@dataclass
class Row:
    market: str
    company: str
    title: str
    locations: list[str]
    urls: list[str]
    fit: str
    matched: list[str]
    route: str | None
    salary: dict | None
    tags: list[str]
    first_seen: str
    new: bool
    applied: dict | None


def is_tagged(row: Row) -> bool:
    """True when the row carries a ghost sign: cloned, stale or ghost history."""
    return any(t.startswith("cloned") or t in GHOST_SIGNS for t in row.tags)


def sponsors_for(entry: dict | None, market: str | None) -> bool:
    """An Irish row with an ie-permit or other sponsor mark; Brazil needs no sponsorship."""
    if market != "IE" or not entry:
        return False
    marks = entry.get("sponsor") or []
    if isinstance(marks, dict):
        marks = [marks]
    return any(isinstance(m, dict) and m.get("type") in IE_SPONSOR_TYPES for m in marks)


def intake_command(url: str) -> str | None:
    """The shell command to paste for a role, or None when the feed URL is not safe to put in one."""
    if not is_web(url) or any(c.isspace() or unicodedata.category(c).startswith("C") for c in url):
        return None
    return "cvforge intake " + shlex.quote(url)


def _url_key(url: str) -> str:
    return canonical_url(url).rstrip("/")


def _tracker_keys(tracker_rows: list[dict]) -> list[tuple[str | None, tuple | None, dict]]:
    """Each tracker row's URL key and (company, title) key, None when blank, normalised once."""
    keys = []
    for row in tracker_rows:
        url = _url_key(row["url"]) if row.get("url") else None
        ident = (name_key(row.get("company") or ""), norm_title(row.get("role") or ""))
        keys.append((url, ident if all(ident) else None, row))
    return keys


def _matches(role: Role, tracker_keys: list[tuple[str | None, tuple | None, dict]]) -> list[dict]:
    url = _url_key(role.url)
    ident = (name_key(role.company), norm_title(role.title))
    return [{"date": row.get("date") or "", "status": row.get("status")}
            for row_url, row_ident, row in tracker_keys
            if (row_url is not None and row_url == url) or (row_ident is not None and row_ident == ident)]


def _best(matches: list[dict]) -> dict | None:
    """An applied-like status beats drafted, which beats skipped; the latest date wins among equals."""
    if not matches:
        return None
    rank = {"drafted": 1, "skipped": 2}
    top = min(rank.get(m["status"], 0) for m in matches)
    return max((m for m in matches if rank.get(m["status"], 0) == top), key=lambda m: m["date"])


def applied_match(role: Role, tracker_rows: list[dict]) -> dict | None:
    return _best(_matches(role, _tracker_keys(tracker_rows)))


def _place(role: Role) -> str:
    return SPACE.sub(" ", fold_accents(role.location or "")).strip()


def _shingles(description: str) -> set:
    words = WORDS.findall(fold_accents(description or ""))
    if len(words) < 3:
        return set(words)
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def _similar(a: set, b: set) -> bool:
    if not a and not b:
        return True
    return len(a & b) / len(a | b) >= CLONE_SIMILARITY


def _clusters(items: list[tuple[Role, Outcome]]) -> list[list[tuple[Role, Outcome]]]:
    """Single-link clusters by description similarity, in first-seen order."""
    shingles = [_shingles(r.description) for r, _ in items]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _similar(shingles[i], shingles[j]):
                parent[find(j)] = find(i)
    grouped: dict[int, list] = {}
    for i, item in enumerate(items):
        grouped.setdefault(find(i), []).append(item)
    return list(grouped.values())


def _unique(values) -> list:
    out: list = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def build_rows(kept: list[tuple[Role, Outcome]], seen: dict[str, dict], *, registry: list[dict],
               ghosts: dict[str, dict], tracker_rows: list[dict], last_viewed: datetime | None,
               now: datetime) -> tuple[list[Row], dict[str, str]]:
    clone_groups: dict[tuple, list] = {}
    for role, out in kept:
        clone_groups.setdefault((name_key(role.company), norm_title(role.title), _place(role)), []).append((role, out))
    units = [c for group in clone_groups.values() for c in _clusters(group)]

    # Units that share a location stay apart (different texts, same place); others fold into one row.
    buckets: dict[tuple, list[list[list]]] = {}
    for unit in units:
        role, out = unit[0]
        bucket = buckets.setdefault((name_key(role.company), norm_title(role.title), out.market), [])
        place = _place(role)
        for row_units in bucket:
            if all(_place(u[0][0]) != place for u in row_units):
                row_units.append(unit)
                break
        else:
            bucket.append([unit])
    merged = [row_units for bucket in buckets.values() for row_units in bucket]

    rows: list[Row] = []
    flagged: dict[str, str] = {}
    today = now.date()
    order: dict[int, int] = {}
    for i, (r, _) in enumerate(kept):
        order.setdefault(id(r), i)
    tracker_keys = _tracker_keys(tracker_rows)
    for group in merged:
        group.sort(key=lambda u: order[id(u[0][0])])
        members = [pair for unit in group for pair in unit]
        roles = [r for r, _ in members]
        first_role, first_out = members[0]
        company = first_role.company
        entry = find_company(registry, company)

        stamps = [seen[r.key]["first_seen"] if r.key in seen else now.isoformat(timespec="seconds") for r in roles]
        stale = any(r.key in seen and is_stale(seen[r.key], now) for r in roles)
        clones = max(len(u) for u in group)

        applied = _best([m for r in roles for m in _matches(r, tracker_keys)])
        tags = _unique(t for _, o in members for t in o.tags)
        if clones >= 2:
            tags.append(f"cloned ×{clones}")
        if stale:
            tags.append("stale")
        if ghost_marked(company, ghosts, entry, today):
            tags.append("ghost history")
        if sponsors_for(entry, first_out.market):
            tags.append("sponsor")
        if applied:
            if applied["status"] in ("drafted", "skipped"):
                tags.append(f"in tracker ({applied['status']})")
            elif applied["date"]:
                tags.append(f"applied on {applied['date']}")
            else:
                tags.append("applied (date unknown)")

        if clones >= 2:
            flagged[company] = "cloned"
        elif stale and flagged.get(company) != "cloned":
            flagged[company] = "stale"

        first_seen = min(stamps)
        locations = _unique(r.location for r in roles if r.location) or [""]
        rows.append(Row(
            market=first_out.market, company=company, title=first_role.title, locations=locations,
            urls=[r.url for r in roles], fit=first_out.fit, matched=list(first_out.matched),
            route=first_out.route, salary=first_role.salary, tags=tags, first_seen=first_seen,
            new=is_new(first_seen, applied, last_viewed), applied=applied))

    rows.sort(key=lambda r: r.first_seen, reverse=True)
    rows.sort(key=lambda r: (MARKET_ORDER.get(r.market, 9), not r.new))
    return rows, flagged

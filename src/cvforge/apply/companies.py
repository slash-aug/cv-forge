"""Company registry: known employers and their visa sponsor marks."""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import yaml

from cvforge.profile.model import ProfileError, load_schema, read_yaml, schema_problems
from cvforge.text import fold_accents

SCHEMA_FILE = "companies.schema.json"
ATS = ("ashby", "greenhouse", "lever", "teamtailor", "gupy", "other")
SPONSOR_TYPES = ("pt-tech-visa", "nl-ind", "uk-sponsor", "ie-permit", "other")
LEGAL_SUFFIXES = frozenset(
    {"ltd", "lda", "inc", "llc", "gmbh", "sa", "s a", "bv", "plc", "ltda", "eireli", "me"}
)
FIELDS = ("name", "aliases", "careers_url", "ats", "sponsor", "notes")
CONNECTORS = frozenset({"of", "for", "and", "the", "&"})
NON_WORD = re.compile(r"[^\w]+")


class CompanyError(ProfileError):
    pass


def name_key(name: str, extra_suffixes: frozenset[str] = frozenset()) -> str:
    """Case, accent and punctuation-insensitive name without trailing legal suffixes."""
    suffixes = LEGAL_SUFFIXES | extra_suffixes
    words = NON_WORD.sub(" ", fold_accents(name)).replace("_", " ").split()
    while len(words) > 1:
        if " ".join(words[-2:]) in suffixes and len(words) > 2:
            cut = 2
        elif words[-1] in suffixes:
            cut = 1
        else:
            break
        if len(words) > cut and words[-cut - 1] in CONNECTORS:
            break  # "Bank of Ireland": the suffix is part of the name
        words = words[:-cut]
    return " ".join(words)


def _problems(registry: list[dict]) -> list[str]:
    return schema_problems(registry, load_schema("cvforge.apply", SCHEMA_FILE))


def load_registry(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    data = read_yaml(path, "company registry")
    if data is None:
        return []
    if isinstance(data, list):
        data = [_stringify(e) for e in data]
    problems = _problems(data)
    if problems:
        raise CompanyError(f"{path}: " + "; ".join(problems))
    return [{"name": e["name"], **_defaults(), **e} for e in data]


def _defaults() -> dict:
    return {"aliases": [], "careers_url": None, "ats": None, "sponsor": [], "notes": ""}


def _stringify(entry):
    """YAML reads an unquoted date as a date object; the schema and callers use ISO strings."""
    if isinstance(entry, dict) and isinstance(entry.get("sponsor"), list):
        entry = {**entry, "sponsor": [
            {**s, "date": s["date"].isoformat()} if isinstance(s, dict)
            and isinstance(s.get("date"), date) else s
            for s in entry["sponsor"]
        ]}
    return entry


def _for_yaml(entry: dict) -> dict:
    out = {k: entry[k] for k in FIELDS if k in entry}
    out["sponsor"] = [{k: date.fromisoformat(v) if k == "date" else v for k, v in s.items()}
                      for s in out.get("sponsor", [])]
    return out


def _save(path: Path, registry: list[dict]) -> None:
    problems = _problems(registry)
    if problems:
        raise CompanyError("; ".join(problems))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump([_for_yaml(e) for e in registry], sort_keys=False,
                          allow_unicode=True, default_flow_style=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def find_company(registry: list[dict], name: str) -> dict | None:
    key = name_key(name)
    if not key:
        return None
    for entry in registry:
        if key in {name_key(n) for n in [entry["name"], *entry.get("aliases", [])]}:
            return entry
    return None


def _ensure(registry: list[dict], name: str) -> dict:
    if not name_key(name):
        raise CompanyError(f"invalid company name '{name}'")
    entry = find_company(registry, name)
    if entry is None:
        entry = {"name": name.strip(), **_defaults()}
        registry.append(entry)
    return entry


def add_company(path: Path, name: str, *, careers_url: str | None = None,
                ats: str | None = None, aliases=()) -> dict:
    """Create the company, or fill in the given fields on an existing one."""
    if ats is not None and ats not in ATS:
        raise CompanyError(f"unknown ats '{ats}'; allowed: {', '.join(ATS)}")
    registry = load_registry(path)
    entry = _ensure(registry, name)
    if careers_url:
        entry["careers_url"] = careers_url
    if ats:
        entry["ats"] = ats
    known = {name_key(entry["name"]), *map(name_key, entry["aliases"])}
    for alias in aliases:
        if name_key(alias) not in known:
            entry["aliases"].append(alias)
            known.add(name_key(alias))
    _save(path, registry)
    return entry


def add_sponsor(path: Path, name: str, *, type: str, source: str, day: date) -> dict:
    if type not in SPONSOR_TYPES:
        raise CompanyError(f"unknown sponsor type '{type}'; allowed: {', '.join(SPONSOR_TYPES)}")
    registry = load_registry(path)
    entry = _ensure(registry, name)
    mark = {"type": type, "source": source, "date": day.isoformat()}
    if mark not in entry["sponsor"]:
        entry["sponsor"].append(mark)
    _save(path, registry)
    return entry


def has_sponsor_mark(entry: dict | None) -> bool:
    return bool(entry and entry.get("sponsor"))

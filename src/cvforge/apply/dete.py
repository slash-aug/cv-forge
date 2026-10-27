"""Irish employment permit statistics (DETE): which companies were issued permits."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

from cvforge.apply import http
from cvforge.apply.companies import _save, load_registry, name_key
from cvforge.apply.http import FetchError, host_of, on_domain

STATS_INDEX = "https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/statistics/"
DETE_DOMAIN = "enterprise.gov.ie"
IE_SUFFIXES = frozenset({"limited", "unlimited company", "dac", "designated activity company",
                         "ireland", "europe", "emea", "uc", "clg"})
MARK_TYPE = "ie-permit"
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
YEAR_PAGE = re.compile(r"employment-permit-statistics-(\d{4})", re.IGNORECASE)
SOURCE_YEAR = re.compile(r"\b(20\d{2})\b")


class DeteError(Exception):
    """The DETE data could not be read."""


@dataclass
class ImportResult:
    year: int
    employers: int
    matched: list[str] = field(default_factory=list)


def dete_key(name: str) -> str:
    return name_key(name, IE_SUFFIXES)


def year_page_links(index_html: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for href in HREF.findall(index_html):
        m = YEAR_PAGE.search(href)
        if m and href.lower().split("?")[0].endswith((".html", "/")):
            out.setdefault(int(m.group(1)), href)
    return out


def xlsx_link(year_html: str) -> str | None:
    for href in HREF.findall(year_html):
        low = href.lower().split("?")[0]
        if "permits-issued-to-companies" in low and low.endswith(".xlsx"):
            return href
    return None


def parse_company_xlsx(data: bytes) -> dict[str, int]:
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types on bad input
        raise DeteError(f"unreadable spreadsheet: {exc}") from exc
    if "Export" not in wb.sheetnames:
        raise DeteError("no 'Export' sheet in the spreadsheet")
    name_col = total_col = None
    out: dict[str, int] = {}
    for row in wb["Export"].iter_rows(values_only=True):
        if name_col is None:
            cells = [str(c).strip().lower() if c is not None else "" for c in row]
            if "employer name" in cells:
                name_col = cells.index("employer name")
                total_col = next((i for i, c in enumerate(cells)
                                  if c.startswith("permits issued grand total")), None)
                if total_col is None:
                    raise DeteError("no 'Permits Issued Grand Total' column")
            continue
        if len(row) <= max(name_col, total_col) or row[name_col] is None:
            continue
        name = str(row[name_col]).strip()
        if not name or name.lower() == "grand total":
            continue
        try:
            out[name] = out.get(name, 0) + int(row[total_col] or 0)
        except (TypeError, ValueError):
            continue
    if name_col is None:
        raise DeteError("no 'Employer Name' header row")
    return out


def _matches(key: str, employers: dict[str, int]) -> int | None:
    """Permit total for a company key: exact DETE name, else DETE names starting with it."""
    if not key:
        return None
    exact = prefix = None
    for name, count in employers.items():
        ekey = dete_key(name)
        if ekey == key:
            exact = (exact or 0) + count
        elif ekey.startswith(key + " "):
            prefix = (prefix or 0) + count
    return exact if exact is not None else prefix


def _cache(data_dir: Path, year: int) -> Path:
    return Path(data_dir) / "sponsors" / f"ie-{year}.json"


def _source(year: int) -> str:
    return f"DETE employment permits issued to companies {year}"


def _fetch_dete(fetch, url: str) -> bytes:
    if not on_domain(host_of(url), DETE_DOMAIN):
        raise FetchError(f"not a {DETE_DOMAIN} URL: {url}")
    return fetch(url)


def import_year(data_dir: Path, year: int, *, fetch=http.get_bytes, file: Path | None = None,
                index_url: str = STATS_INDEX) -> ImportResult:
    data_dir = Path(data_dir)
    if file is not None:
        data, source = Path(file).read_bytes(), str(Path(file).name)
    else:
        index = _fetch_dete(fetch, index_url).decode("utf-8", errors="replace")
        page = year_page_links(index).get(year)
        if page is None:
            raise FetchError(f"no DETE statistics page for {year}")
        page_url = urljoin(index_url, page)
        link = xlsx_link(_fetch_dete(fetch, page_url).decode("utf-8", errors="replace"))
        if link is None:
            raise FetchError(f"no companies spreadsheet on {page_url}")
        source = urljoin(page_url, link)
        data = _fetch_dete(fetch, source)
    employers = parse_company_xlsx(data)
    cache = _cache(data_dir, year)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"year": year, "source": source,
                                 "fetched": date.today().isoformat(), "employers": employers},
                                ensure_ascii=False), encoding="utf-8")
    matched = _mark_registry(data_dir / "companies.yaml", year, employers)
    return ImportResult(year, len(employers), matched)


def _mark_registry(path: Path, year: int, employers: dict[str, int]) -> list[str]:
    registry = load_registry(path)
    matched: list[str] = []
    today = date.today().isoformat()
    for entry in registry:
        counts = [c for n in [entry["name"], *entry.get("aliases", [])]
                  if (c := _matches(dete_key(n), employers)) is not None]
        if not counts:
            continue
        mark = {"type": MARK_TYPE, "source": _source(year), "date": today, "count": max(counts)}
        entry["sponsor"] = [s for s in entry["sponsor"]
                            if not (s["type"] == MARK_TYPE and s["source"] == mark["source"])]
        entry["sponsor"].append(mark)
        matched.append(entry["name"])
    if matched:
        _save(path, registry)
    return matched


def _cached_years(data_dir: Path) -> list[tuple[int, Path]]:
    found = []
    for p in (Path(data_dir) / "sponsors").glob("ie-*.json"):
        m = re.fullmatch(r"ie-(\d{4})\.json", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found, reverse=True)


def _read_cache(path: Path) -> dict[str, int] | None:
    try:
        employers = json.loads(path.read_text(encoding="utf-8"))["employers"]
        return employers if isinstance(employers, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def dete_imported(data_dir: Path) -> bool:
    return any(_read_cache(p) is not None for _, p in _cached_years(data_dir))


def permit_record(data_dir: Path, company_name: str, registry_entry: dict | None
                  ) -> tuple[int, int] | None:
    """(year, count) for the newest year with a match, from the registry mark or the cache."""
    best: tuple[int, int] | None = None
    for s in (registry_entry or {}).get("sponsor", []):
        if s.get("type") == MARK_TYPE and "count" in s:
            m = SOURCE_YEAR.search(s.get("source", ""))
            if m and (best is None or int(m.group(1)) > best[0]):
                best = (int(m.group(1)), s["count"])
    key = dete_key(company_name)
    for year, path in _cached_years(data_dir):
        if best and year <= best[0]:
            break
        employers = _read_cache(path)
        count = _matches(key, employers) if employers else None
        if count is not None:
            return year, count
    return best

"""requirements.yaml: the facts Claude quotes from a posting, and the quote check."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from cvforge.profile.model import ProfileError, load_schema, read_yaml, schema_problems

SCHEMA_FILE = "requirements.schema.json"
QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    **{chr(c): "-" for c in range(0x2010, 0x2016)}, "−": "-",
})
SPACES = re.compile(r"\s+")
EMPTY_SALARY = {"min": None, "max": None, "currency": None, "period": None,
                "contract": "unknown", "quote": None}


class RequirementsError(ProfileError):
    pass


def normalise_quote(text: str) -> str:
    """NFKC, casefold, straight quotes, ASCII hyphens, one space per whitespace run."""
    text = unicodedata.normalize("NFKC", text).casefold().translate(QUOTES)
    return SPACES.sub(" ", text.replace(" ", " ")).strip()


def _rule_problems(req: dict) -> list[str]:
    problems = []
    sponsorship = req["sponsorship"]
    if sponsorship["status"] != "silent" and not sponsorship.get("quote"):
        problems.append(f"sponsorship.quote: required when status is {sponsorship['status']}")
    salary = req["salary"]
    if salary.get("min") is not None or salary.get("max") is not None:
        for key in ("currency", "period", "quote"):
            if not salary.get(key):
                problems.append(f"salary.{key}: required when a salary figure is stated")
    return problems


def load_requirements(path: Path) -> dict:
    data = read_yaml(path, "requirements")
    if isinstance(data, dict) and isinstance(data.get("salary"), dict):
        contract = data["salary"].get("contract")
        if isinstance(contract, str):
            data["salary"]["contract"] = contract.strip().lower()
    problems = schema_problems(data, load_schema("cvforge.apply", SCHEMA_FILE))
    if not problems:
        data["salary"] = {**EMPTY_SALARY, **(data.get("salary") or {})}
        data.setdefault("languages_required", [])
        data["location"].setdefault("quote", None)
        data["sponsorship"].setdefault("quote", None)
        problems = _rule_problems(data)
    if problems:
        raise RequirementsError(f"{path}: " + "; ".join(problems))
    return data


def _quotes(req: dict):
    """Yield (field path, quote) for every non-empty quote, in document order."""
    for i, item in enumerate(req.get("years") or []):
        yield f"years.{i}.quote", item.get("quote")
    for key in ("location", "sponsorship", "salary"):
        yield f"{key}.quote", (req.get(key) or {}).get("quote")
    for i, item in enumerate(req.get("languages_required") or []):
        yield f"languages_required.{i}.quote", item.get("quote")


def quote_problems(req: dict, posting_text: str) -> list[str]:
    haystack = normalise_quote(posting_text)
    problems = []
    for where, quote in _quotes(req):
        if quote is None:
            continue
        needle = normalise_quote(quote)
        if not needle:
            problems.append(f"{where}: empty quote")
        elif needle not in haystack:
            problems.append(f'{where}: not in the posting: "{quote}"')
    return problems


def posting_text(posting) -> str:
    """Every posting field Claude may quote from: title, location, salary text, description."""
    parts = [posting.title, posting.location, *posting.location_requirements,
             posting.workplace or ""]
    if isinstance(posting.salary, dict):
        parts += [str(v) for v in posting.salary.values() if v is not None]
    parts.append(posting.description)
    return "\n".join(p for p in parts if p)

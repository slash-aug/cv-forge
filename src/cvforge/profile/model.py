import json
from collections import Counter
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_FILE = "master.schema.json"


class ProfileError(ValueError):
    pass


def load_schema(package: str = "cvforge.profile", filename: str = SCHEMA_FILE) -> dict:
    text = resources.files(package).joinpath(filename).read_text(encoding="utf-8")
    return json.loads(text)


def _format_path(parts) -> str:
    return ".".join(str(p) for p in parts) or "(root)"


DATE_KEYS = {"startDate", "endDate", "date"}


def _date_hint(error) -> str:
    path = list(error.absolute_path)
    if not path or path[-1] not in DATE_KEYS:
        return ""
    if path[0] == "education":
        return ' (use a quoted "YYYY" or "YYYY-MM" string)'
    nullable = " or null" if path[-1] == "endDate" else ""
    return f' (use a quoted "YYYY-MM" string{nullable})'


def _unexpected_keys_message(error) -> str:
    allowed = error.schema["properties"]
    extra = sorted(k for k in error.instance if k not in allowed)
    keys = ", ".join(repr(k) for k in extra)
    return f"unexpected key {keys}; allowed: {', '.join(allowed)}"


def _relevant_error(error):
    """Descend into anyOf to the sub-error that explains the failure, if any branch has one."""
    while error.context:
        specific = [e for e in error.context if e.validator != "type"]
        if not specific:
            return error
        error = max(specific, key=lambda e: len(e.absolute_path))
    return error


def _describe(error) -> str:
    leaf = _relevant_error(error)
    if leaf.validator == "additionalProperties" and "properties" in leaf.schema:
        message = _unexpected_keys_message(leaf)
    elif leaf.context:
        message = f"{leaf.instance!r} has the wrong type"
    else:
        message = leaf.message
    return f"{_format_path(error.absolute_path)}: {message}{_date_hint(error)}"


def schema_problems(data, schema: dict) -> list[str]:
    """Readable, path-prefixed schema violations, sorted by path (shared with the tailored loader)."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    return [_describe(e) for e in errors]


def read_yaml(path: Path, what: str):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        raise ProfileError(f"{path}: cannot read {what}: {e}") from e


def _iter_items(master: dict):
    """Yield (kind, item) for every id-bearing item, in document order."""
    for item in master.get("x-summaries", []):
        yield "summary", item
    for employer in master.get("work", []):
        yield "work", employer
        for position in employer.get("positions", []):
            yield "position", position
            for highlight in position.get("highlights", []):
                yield "highlight", highlight
    for kind, key in (
        ("skill", "skills"),
        ("education", "education"),
        ("certificate", "certificates"),
        ("language", "languages"),
    ):
        for item in master.get(key, []):
            yield kind, item


def _duplicate_id_problems(master: dict) -> list[str]:
    counts = Counter(item["id"] for _, item in _iter_items(master))
    return [f"duplicate id '{item_id}' ({n} times)" for item_id, n in counts.items() if n > 1]


def load_master(path: Path) -> dict:
    master = read_yaml(path, "master profile")
    problems = schema_problems(master, load_schema())
    if not problems:
        problems = _duplicate_id_problems(master)
    if problems:
        raise ProfileError(f"{path}: " + "; ".join(problems))
    return master


def localized(value: str | dict, lang: str, *, item_id: str) -> str:
    if isinstance(value, str):
        return value
    if lang not in value:
        raise ProfileError(f"{item_id}: missing translation '{lang}'")
    return value[lang]


def index(master: dict) -> dict[str, tuple[str, dict]]:
    return {item["id"]: (kind, item) for kind, item in _iter_items(master)}

"""Tailored selection loader and grounding audit against the master profile."""
import re
from dataclasses import dataclass
from pathlib import Path

from cvforge.profile.model import (
    ProfileError,
    index,
    load_schema,
    read_yaml,
    schema_problems,
)

SCHEMA_FILE = "tailored.schema.json"
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Finding:
    kind: str
    ref: str
    message: str


def load_tailored(path: Path) -> dict:
    tailored = read_yaml(path, "tailored selection")
    problems = schema_problems(tailored, load_schema("cvforge.tailor", SCHEMA_FILE))
    if problems:
        raise ProfileError(f"{path}: " + "; ".join(problems))
    return tailored


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in NUMBER.findall(text)}


def _texts(value) -> list[str]:
    """Every locale variant of a localized value (plain string or locale dict)."""
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value.values())


def _highlight_numbers(highlight: dict) -> set[str]:
    found: set[str] = set()
    for key in ("impact", "technical"):
        for text in _texts(highlight.get(key)):
            found |= _numbers(text)
    return found


def _strings(tailored: dict):
    """Yield (location, text) for every free-text string, in document order."""
    target = tailored.get("target", {})
    for key in ("company", "role"):
        yield f"target.{key}", target.get(key, "")
    yield "summary", tailored.get("summary", {}).get("text", "")
    for work in tailored.get("experience", []):
        for position in work.get("positions", []):
            for bullet in position.get("bullets", []):
                yield bullet.get("ref", "bullet"), bullet.get("text", "")
    for skill in tailored.get("skills", []):
        for keyword in skill.get("keywords", []):
            yield skill.get("ref", "skill"), keyword
    letter = tailored.get("letter") or {}
    for key in ("recipient", "opening", "closing"):
        yield f"letter.{key}", letter.get(key, "")
    for i, paragraph in enumerate(letter.get("paragraphs", [])):
        yield f"letter.paragraphs.{i}", paragraph


def _resolve(ids: dict, ref, kind: str, findings: list[Finding]):
    entry = ids.get(ref)
    if entry is None or entry[0] != kind:
        found = "no such id" if entry is None else f"is a {entry[0]}"
        findings.append(Finding("unknown-ref", str(ref), f"expected a {kind} id, {found}"))
        return None
    return entry[1]


def _check_numbers(ref: str, text: str, allowed: set[str], findings: list[Finding]):
    extra = sorted(_numbers(text) - allowed)
    if extra:
        findings.append(
            Finding("number", ref, f"not in the master text: {', '.join(extra)}")
        )


def _audit_experience(tailored: dict, ids: dict, findings: list[Finding]):
    for work_sel in tailored.get("experience", []):
        work = _resolve(ids, work_sel.get("ref"), "work", findings)
        for pos_sel in work_sel.get("positions", []):
            position = _resolve(ids, pos_sel.get("ref"), "position", findings)
            if position is not None and work is not None and position not in work["positions"]:
                findings.append(
                    Finding("wrong-parent", pos_sel["ref"], f"not a position of {work['id']}")
                )
            for bullet in pos_sel.get("bullets", []):
                highlight = _resolve(ids, bullet.get("ref"), "highlight", findings)
                if highlight is None:
                    continue
                if position is not None and highlight not in position["highlights"]:
                    findings.append(
                        Finding("wrong-parent", bullet["ref"], f"not a highlight of {position['id']}")
                    )
                _check_numbers(
                    bullet["ref"], bullet.get("text", ""), _highlight_numbers(highlight), findings
                )


def _audit_summary(tailored: dict, master: dict, ids: dict, findings: list[Finding]):
    selection = tailored.get("summary", {})
    summary = _resolve(ids, selection.get("ref"), "summary", findings)
    if summary is None:
        return
    allowed: set[str] = set()
    for text in _texts(summary.get("text")):
        allowed |= _numbers(text)
    for kind, item in ids.values():
        if kind == "highlight":
            allowed |= _highlight_numbers(item)
    _check_numbers(selection["ref"], selection.get("text", ""), allowed, findings)


def _audit_skills(tailored: dict, ids: dict, findings: list[Finding]):
    for selection in tailored.get("skills", []):
        skill = _resolve(ids, selection.get("ref"), "skill", findings)
        if skill is None:
            continue
        for keyword in selection.get("keywords", []):
            if keyword not in skill["keywords"]:
                findings.append(
                    Finding("skill-keyword", selection["ref"], f"'{keyword}' is not a keyword of this skill")
                )


def _audit_id_lists(tailored: dict, ids: dict, findings: list[Finding]):
    for key, kind in (("education", "education"), ("certificates", "certificate"), ("languages", "language")):
        for ref in tailored.get(key, []):
            _resolve(ids, ref, kind, findings)


def _audit_confidential(tailored: dict, master: dict, findings: list[Finding]):
    terms = [t for t in master.get("x-confidential", []) if t]
    for location, text in _strings(tailored):
        lowered = text.lower()
        for term in terms:
            if term.lower() in lowered:
                findings.append(Finding("confidential", location, f"contains confidential term '{term}'"))


def audit(tailored: dict, master: dict) -> list[Finding]:
    """Grounding findings in document order (confidential scan last); empty means grounded."""
    ids = index(master)
    findings: list[Finding] = []
    _audit_summary(tailored, master, ids, findings)
    _audit_experience(tailored, ids, findings)
    _audit_skills(tailored, ids, findings)
    _audit_id_lists(tailored, ids, findings)
    _audit_confidential(tailored, master, findings)
    return findings

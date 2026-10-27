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
from cvforge.text import contains_term

SCHEMA_FILE = "tailored.schema.json"
EM_DASH = "\u2014"
CONNECT_LIMIT = 160
MESSAGE_LIMIT = 1200
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


def figures(*texts: str) -> set[str]:
    """The numbers in texts, in the form the audit compares (for audit's extra_allowed)."""
    return set().union(*(_numbers(t) for t in texts))


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


def _para_text(paragraph) -> str:
    return paragraph if isinstance(paragraph, str) else paragraph.get("text", "")


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
        yield f"letter.paragraphs.{i}", _para_text(paragraph)
    note = tailored.get("recruiter_note") or {}
    for key in ("connect", "message"):
        if key in note:
            yield f"recruiter_note.{key}", note[key]
    for i, answer in enumerate(tailored.get("answers", [])):
        yield f"answers.{i}.answer", answer.get("answer", "")
    email = tailored.get("email") or {}
    for key in ("subject", "body"):
        if key in email:
            yield f"email.{key}", email[key]


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
            if position is not None and work is not None and position["id"] not in {
                p["id"] for p in work["positions"]
            }:
                findings.append(
                    Finding("wrong-parent", pos_sel["ref"], f"not a position of {work['id']}")
                )
            for bullet in pos_sel.get("bullets", []):
                highlight = _resolve(ids, bullet.get("ref"), "highlight", findings)
                if highlight is None:
                    continue
                if position is not None and highlight["id"] not in {h["id"] for h in position["highlights"]}:
                    findings.append(
                        Finding("wrong-parent", bullet["ref"], f"not a highlight of {position['id']}")
                    )
                _check_numbers(
                    bullet["ref"], bullet.get("text", ""), _highlight_numbers(highlight), findings
                )


def _audit_summary(tailored: dict, ids: dict, findings: list[Finding]):
    selection = tailored.get("summary", {})
    summary = _resolve(ids, selection.get("ref"), "summary", findings)
    if summary is None:
        return
    _check_numbers(
        selection["ref"], selection.get("text", ""), _broad_numbers(ids, summary), findings
    )


def _broad_numbers(ids: dict, summary: dict | None = None) -> set[str]:
    """Numbers allowed in free prose: all highlights plus the given summary (or every summary)."""
    allowed: set[str] = set()
    for kind, item in ids.values():
        if kind == "highlight":
            allowed |= _highlight_numbers(item)
        elif kind == "summary" and (summary is None or item is summary):
            for text in _texts(item.get("text")):
                allowed |= _numbers(text)
    return allowed


def _ref_numbers(refs: list, ids: dict, findings: list[Finding]) -> set[str]:
    """Numbers found in the cited highlights and summaries; unknown refs become findings."""
    allowed: set[str] = set()
    for ref in refs:
        entry = ids.get(ref)
        if entry is None or entry[0] not in ("highlight", "summary"):
            found = "no such id" if entry is None else f"is a {entry[0]}"
            findings.append(
                Finding("unknown-ref", str(ref), f"expected a highlight or summary id, {found}")
            )
        elif entry[0] == "highlight":
            allowed |= _highlight_numbers(entry[1])
        else:
            for text in _texts(entry[1].get("text")):
                allowed |= _numbers(text)
    return allowed


def _check_prose(location: str, text: str, refs: list | None, ids: dict, findings: list[Finding],
                 extra: set[str] | frozenset[str] = frozenset()):
    """Text with refs may only use numbers from them; text without keeps the broad rule."""
    if refs:
        allowed = _ref_numbers(refs, ids, findings)
    else:
        allowed = _broad_numbers(ids)
    _check_numbers(location, text, allowed | set(extra), findings)


def _audit_letter(tailored: dict, ids: dict, findings: list[Finding]):
    letter = tailored.get("letter") or {}
    _check_prose("letter.opening", letter.get("opening", ""), None, ids, findings)
    for i, paragraph in enumerate(letter.get("paragraphs", [])):
        refs = paragraph.get("refs") if isinstance(paragraph, dict) else None
        _check_prose(f"letter.paragraphs.{i}", _para_text(paragraph), refs, ids, findings)
    _check_prose("letter.closing", letter.get("closing", ""), None, ids, findings)


def _audit_note_and_answers(tailored: dict, ids: dict, findings: list[Finding],
                            extra_allowed: set[str] | frozenset[str]):
    note = tailored.get("recruiter_note")
    if note:
        refs = note.get("refs")
        for key, limit in (("connect", CONNECT_LIMIT), ("message", MESSAGE_LIMIT)):
            text = note.get(key, "")
            _check_prose(f"recruiter_note.{key}", text, refs, ids, findings)
            if len(text) > limit:
                extra = (
                    " (LinkedIn's free limit is 200, we keep a margin)" if key == "connect" else ""
                )
                findings.append(
                    Finding("length", f"recruiter_note.{key}", f"{len(text)} characters, limit {limit}{extra}")
                )
    for i, answer in enumerate(tailored.get("answers", [])):
        location = f"answers.{i}.answer"
        text = answer.get("answer", "")
        _check_prose(location, text, answer.get("refs"), ids, findings, extra_allowed)
        limit = answer.get("limit")
        if limit is not None and len(text) > limit:
            findings.append(Finding("length", location, f"{len(text)} characters, limit {limit}"))


def _audit_email(tailored: dict, ids: dict, findings: list[Finding]):
    email = tailored.get("email")
    if email:
        for key in ("subject", "body"):
            _check_prose(f"email.{key}", email.get(key, ""), email.get("refs"), ids, findings)


def _audit_em_dash(tailored: dict, findings: list[Finding]):
    for location, text in _strings(tailored):
        if EM_DASH in text:
            findings.append(Finding("em-dash", location, "contains an em dash"))


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
        for term in terms:
            if contains_term(text, term):
                findings.append(Finding("confidential", location, f"contains confidential term '{term}'"))


def _leaves(value, path: str):
    """Yield (dotted path, string) for every string inside nested dicts and lists."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _leaves(item, f"{path}.{i}")


def audit_rendered(master: dict, **rendered: dict | None) -> list[Finding]:
    """Confidential terms in any value about to be rendered, master-derived fields included.

    Each keyword names a document (cv=view, letter=context); a finding's ref is the
    field path, such as cv.experience.0.employer.
    """
    terms = [t for t in master.get("x-confidential", []) if t]
    return [
        Finding("confidential", location, f"contains confidential term '{term}'")
        for name, value in rendered.items()
        for location, text in _leaves(value, name)
        for term in terms
        if contains_term(text, term)
    ]


def audit(tailored: dict, master: dict, *,
          extra_allowed: set[str] | frozenset[str] = frozenset()) -> list[Finding]:
    """Grounding findings in document order (confidential scan last); empty means grounded.

    extra_allowed: numbers (as figures() returns them) also allowed in screening answers only,
    such as knock-out facts computed from master dates and a confirmed salary.
    """
    ids = index(master)
    findings: list[Finding] = []
    _audit_summary(tailored, ids, findings)
    _audit_experience(tailored, ids, findings)
    _audit_skills(tailored, ids, findings)
    _audit_id_lists(tailored, ids, findings)
    _audit_letter(tailored, ids, findings)
    _audit_note_and_answers(tailored, ids, findings, extra_allowed)
    _audit_email(tailored, ids, findings)
    _audit_em_dash(tailored, findings)
    _audit_confidential(tailored, master, findings)
    return findings


def audit_answer(question: str, answer: str, master: dict, *,
                 extra_allowed: set[str] | frozenset[str] = frozenset(),
                 limit: int | None = None) -> list[Finding]:
    """Findings for one typed screening answer: numbers (broad rule, no refs), em dash,
    confidential terms in question or answer, and length over limit."""
    findings: list[Finding] = []
    allowed = _broad_numbers(index(master)) | set(extra_allowed)
    _check_numbers("answer", answer, allowed, findings)
    if EM_DASH in answer:
        findings.append(Finding("em-dash", "answer", "contains an em dash"))
    for location, text in (("question", question), ("answer", answer)):
        for term in (t for t in master.get("x-confidential", []) if t):
            if contains_term(text, term):
                findings.append(
                    Finding("confidential", location, f"contains confidential term '{term}'")
                )
    if limit is not None and len(answer) > limit:
        findings.append(Finding("length", "answer", f"{len(answer)} characters, limit {limit}"))
    return findings

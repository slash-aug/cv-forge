"""Work descriptions for application forms, cut only between lines or sentences."""
from __future__ import annotations

import re

from cvforge.profile.model import positions, text_in

LANGS = ("en", "pt-BR", "pt-PT")
FIRST_VARIANT = 200
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _fit_sentences(line: str, limit: int) -> str:
    out = ""
    for sentence in _SENTENCE_END.split(line):
        candidate = f"{out} {sentence}" if out else sentence
        if len(candidate) > limit:
            break
        out = candidate
    return out


def cut(text: str, limit: int) -> str:
    """At most `limit` characters: whole lines, else whole sentences of the first line, else nothing."""
    if len(text) <= limit:
        return text
    kept: list[str] = []
    for line in text.split("\n"):
        if len("\n".join([*kept, line])) > limit:
            break
        kept.append(line)
    if kept:
        return "\n".join(kept)
    return _fit_sentences(text.split("\n", 1)[0], limit)


def _pinned_line(pin: dict, full: str, lang: str) -> tuple[str, str | None]:
    short = text_in(pin.get("short"), lang)
    return f"- {full}", f"- {short}" if short else None


def _form_lines(position: dict, bullets: list[dict], lang: str) -> list[tuple[str, str | None]] | None:
    """(line, shorter line) in priority order, or None when there is no form text in `lang`."""
    form = position.get("x-form") or {}
    context = text_in(form.get("context"), lang)
    if context is None:
        return None
    tailored = {b["ref"]: b["text"] for b in bullets}
    highlights = {h["id"]: h for h in position["highlights"]}
    lines: list[tuple[str, str | None]] = [(context, None)]
    for pin in form["pinned"]:
        full = tailored.get(pin["ref"]) or text_in(highlights[pin["ref"]]["impact"], lang)
        if full is not None:
            lines.append(_pinned_line(pin, full, lang))
    pinned = {pin["ref"] for pin in form["pinned"]}
    lines.extend((f"- {b['text']}", None) for b in bullets if b["ref"] not in pinned)
    return lines


def describe(position: dict, bullets: list[dict], lang: str, limit: int) -> str:
    """One position's description for a field of `limit` characters.

    With form text: the context, the pinned highlights, then the other bullets, filled in
    that order until a line does not fit. Without it: the bullets as selected.
    """
    lines = _form_lines(position, bullets, lang)
    if lines is None:
        return cut("\n".join(f"- {b['text']}" for b in bullets), limit)
    kept: list[str] = []
    for full, short in lines:
        fitting = next((c for c in (full, short)
                        if c and len("\n".join([*kept, c])) <= limit), None)
        if fitting is None:
            break
        kept.append(fitting)
    return "\n".join(kept)


def first_variant_size(position: dict, bullets: list[dict], lang: str) -> int | None:
    """Characters the context plus the first pinned line need, at their shortest.

    None without form text in `lang`, without a pinned highlight, or when the first one
    has no text in `lang`.
    """
    form = position.get("x-form") or {}
    context = text_in(form.get("context"), lang)
    if context is None or not form["pinned"]:
        return None
    pin = form["pinned"][0]
    full = next((b["text"] for b in bullets if b["ref"] == pin["ref"]), None)
    if full is None:
        highlight = next(h for h in position["highlights"] if h["id"] == pin["ref"])
        full = text_in(highlight["impact"], lang)
    if full is None:
        return None
    return len(context) + 1 + min(len(c) for c in _pinned_line(pin, full, lang) if c)


def form_length_problems(master: dict) -> list[str]:
    """Form text that cannot fit the first variant. Only `validate` fails on these."""
    problems = []
    for position in positions(master):
        form = position.get("x-form")
        if not form:
            continue
        for lang in LANGS:
            context = text_in(form["context"], lang)
            if context is None:
                continue
            where = f"{position['id']} ({lang})"
            if len(context) > FIRST_VARIANT:
                problems.append(
                    f"{where}: context is {len(context)} characters, limit {FIRST_VARIANT}")
            elif (size := first_variant_size(position, [], lang)) and size > FIRST_VARIANT:
                problems.append(f"{where}: context plus first pinned line is {size} characters, "
                                f"limit {FIRST_VARIANT}")
    return problems

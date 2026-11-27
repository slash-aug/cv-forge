"""Work descriptions for application forms, cut only between lines or sentences."""
from __future__ import annotations

import re

from cvforge.profile.model import text_in

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


def _form_lines(position: dict, bullets: list[dict], lang: str) -> list[tuple[str, str | None]] | None:
    """(line, shorter line) in priority order, or None when there is no form text in `lang`."""
    form = position.get("x-form") or {}
    context = text_in(form.get("context"), lang)
    if context is None:
        return None
    tailored = {b["ref"]: b["text"] for b in bullets}
    highlights = {h["id"]: h for h in position["highlights"]}
    lines: list[tuple[str, str | None]] = [(context, None)]
    pinned = set()
    for pin in form["pinned"]:
        ref = pin["ref"]
        pinned.add(ref)
        full = tailored.get(ref) or text_in(highlights[ref]["impact"], lang)
        if full is None:
            continue
        short = text_in(pin.get("short"), lang)
        lines.append((f"- {full}", f"- {short}" if short else None))
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

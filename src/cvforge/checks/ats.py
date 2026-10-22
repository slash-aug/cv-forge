"""ATS check of a compiled PDF: page count, text-layer sanity, dates, layout."""
from __future__ import annotations

from collections.abc import Sequence
import re
from dataclasses import dataclass, field
from pathlib import Path

from cvforge.checks import layout
from cvforge.checks.textlayer import (
    VerificationError,
    extract_text_layer,
    find_non_ascii_date_ranges,
    normalize_text,
)

LAYOUT_SKIPPED = "layout check skipped: pdftotext not installed"


@dataclass
class AtsReport:
    """Result of `ats_check`.

    `problems` holds real problems plus, when the layout check could not run, one
    informational skip note that starts with "layout check skipped". The skip
    note never makes `ok` False: `ok` is True exactly when `problems` contains
    nothing but skip notes.
    """

    ok: bool
    problems: list[str] = field(default_factory=list)
    text: str = ""
    pages: int = 0
    extractor: str = ""


def _is_note(problem: str) -> bool:
    return problem.startswith("layout check skipped")


def _heading_order_problem(text: str, headings: Sequence[str]) -> str | None:
    """Headings must each start a line, in the given order."""
    lines = "\n".join(normalize_text(line) for line in text.splitlines())
    pos = 0
    for heading in headings:
        pattern = rf"(?m)^[^\S\n]*{re.escape(normalize_text(heading))}(?!\w)"
        match = re.compile(pattern).search(lines, pos)
        if match is None:
            return f"heading {heading!r} not found at a line start, in order"
        pos = match.end()
    return None


def _layout_problems(pdf: Path) -> list[str]:
    if layout.find_pdftotext() is None:
        return [LAYOUT_SKIPPED]
    try:
        return [f"layout: {m}" for m in layout.find_orphans(layout.parse_pdf(pdf))]
    except (RuntimeError, OSError) as exc:
        return [f"layout check skipped: {exc}"]


def ats_check(
    pdf: Path,
    *,
    max_pages: int,
    exact_pages: bool = False,
    required: Sequence[str] = (),
    headings: Sequence[str] = (),
) -> AtsReport:
    """Check a PDF for ATS safety. Never raises on a bad document, only reports."""
    pdf = Path(pdf)
    try:
        text, pages, extractor = extract_text_layer(pdf)
    except VerificationError as exc:
        return AtsReport(False, [f"text layer unreadable: {exc}"], "", 0, "")

    problems: list[str] = []
    if exact_pages and pages != max_pages:
        problems.append(f"expected exactly {max_pages} page(s), found {pages}")
    elif pages > max_pages:
        problems.append(f"{pages} page(s) exceeds the maximum of {max_pages}")
    if "(cid:" in text:
        problems.append("text layer contains '(cid:' (unmapped glyphs)")
    if "�" in text:
        problems.append("text layer contains U+FFFD (replacement character)")
    hits = find_non_ascii_date_ranges(text)
    if hits:
        listed = "; ".join(f"U+{ord(d):04X} in {line[:80]!r}" for line, d in hits)
        problems.append(
            f"{len(hits)} date range(s) joined by a non-ASCII dash, use an ASCII hyphen: {listed}"
        )
    norm = normalize_text(text)
    for req in required:
        if normalize_text(req) not in norm:
            problems.append(f"required text missing: {req!r}")
    order = _heading_order_problem(text, headings)
    if order:
        problems.append(order)
    problems.extend(_layout_problems(pdf))

    ok = not any(not _is_note(p) for p in problems)
    return AtsReport(ok, problems, text, pages, extractor)

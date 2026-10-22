# Ported from ai-job-search (MIT): tools/verify_pdf.py
"""Text-layer helpers for ATS checks: extraction, comparison folding, date ranges."""
import re
import shutil
import subprocess
import unicodedata


class VerificationError(Exception):
    """Raised when a generated PDF does not satisfy its checks."""


def run_tool(command):
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    except FileNotFoundError as exc:
        raise VerificationError(
            f"required command '{command[0]}' was not found. "
            "Install poppler-utils (macOS: brew install poppler, Debian/Ubuntu: apt install poppler-utils, "
            "Windows: choco install poppler)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or (exc.stdout or "").strip()
        detail = detail or "command failed"
        raise VerificationError(f"{command[0]} could not read the PDF: {detail}") from exc


def parse_page_count(pdfinfo_output):
    match = re.search(r"^Pages:\s+(\d+)\s*$", pdfinfo_output, re.MULTILINE)
    if not match:
        raise VerificationError("pdfinfo output did not contain a page count")
    return int(match.group(1))


# Typographic substitutions the moderncv/cover.cls templates produce from plain
# source text, mapped back to what a user types as a required string. LaTeX ligatures
# ' into U+2019 and -- into U+2013, so "Master's degree" and "2016-2024" are
# absent from the text layer of a CV that plainly contains them. Applied
# to both sides of the comparison; the extracted dump is never rewritten.
TYPOGRAPHIC_FOLDS = str.maketrans(
    {
        "\u2018": "'",  # ` -> quoteleft
        "\u2019": "'",  # ' -> quoteright (the possessive apostrophe)
        "\u201c": '"',  # `` -> quotedblleft
        "\u201d": '"',  # '' -> quotedblright
        "\u2013": "-",  # -- -> endash (the \cventry date-range case)
        "\u2014": "-",  # --- -> emdash
        "\u00a0": " ",  # ~ -> no-break space
    }
)


def normalize_text(text):
    """Fold a string for comparison: NFC, typographic punctuation, whitespace.

    NFC covers the pdflatex text layer, which without T1 font encoding stores
    accented letters decomposed (`e` + U+0300) while a user types them
    precomposed (U+00E8); both forms fold to the same string. The fold
    applies to what is compared, never to the raw layer: the date-range rule
    still needs the raw en-dash visible.
    """
    text = unicodedata.normalize("NFC", text).translate(TYPOGRAPHIC_FOLDS)
    return " ".join(text.split())


# Dash-like code points a year must never be joined to in a date range. U+2013 is
# what LaTeX makes from `--` and what a Workday import dropped; the
# rest are the other Unicode dashes and the minus sign, which a parser that splits
# a range only on U+002D treats the same way.
NON_ASCII_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"
# A year is four digits standing alone: without the digit boundaries, `2000`
# inside `120000` or `12000` made a budget or throughput range read as a date.
_YEAR = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
# Horizontal whitespace only between the year and the dash: `\s*` also matched
# a newline, so a year ending one line joined a dash opening the next (a bullet,
# a wrapped prose line) and an ASCII date was reported as U+2013.
NON_ASCII_DATE_RANGE = re.compile(
    rf"{_YEAR}[^\S\n]*[{NON_ASCII_DASHES}]|[{NON_ASCII_DASHES}][^\S\n]*{_YEAR}"
)
# The whitespace-delimited tokens touching the dash on either side. A range whose
# two ends are both BARE numbers is a date only when both are years: `EUR 1500-2000`
# and `2000-5000 requests/s` are quantities that happen to contain a year-shaped
# number, and `--` is legitimate in exactly those. A composite
# token (`03/2016`, `01.2016`, `2016-03`, `2016/17`) is not a bare number, so a
# numerically formatted date range still falls through to the year rule.
_TOKEN_BEFORE = re.compile(r"(\S+)[^\S\n]*$")
_TOKEN_AFTER = re.compile(r"^[^\S\n]*(\S+)")
_BARE_NUMBER = re.compile(r"\d+(?:[.,]\d+)*[kKmM%]?")
_BARE_YEAR = re.compile(r"(?:19|20)\d{2}")
_OUTER_PUNCTUATION = ".,;:!?()[]{}\"'"


def _bare_number(token):
    """The token with outer punctuation stripped, if it is a bare number, else None.

    A dotted or comma-separated token whose groups include a year (`01.2016`,
    `31.07.2024`) is a date written numerically, not a quantity, and is left to
    the year rule; `1,234.56` and `2.0M` have no year group and stay numbers.
    """
    core = token.strip(_OUTER_PUNCTUATION)
    if not _BARE_NUMBER.fullmatch(core):
        return None
    groups = re.split(r"[.,]", core.rstrip("kKmM%"))
    if len(groups) > 1 and any(_BARE_YEAR.fullmatch(g) for g in groups):
        return None
    return core


_TWO_DIGIT_YEAR = re.compile(r"\d{2}")


def _quantity_range(line, dash_index):
    """True when both sides of the dash are bare numbers and not a date pair.

    A date pair is two years (`2016-2024`) or a year and a two-digit year
    (`2016-17`, `2019-20`): the short form is how academic years and seasons
    are written, and it was caught before the quantity rule existed. Anything
    else with bare numbers on both sides is a quantity (`1500-2000`,
    `2000-5000`) and is left alone.
    """
    before = _TOKEN_BEFORE.search(line[:dash_index])
    after = _TOKEN_AFTER.search(line[dash_index + 1 :])
    if not before or not after:
        return False
    left, right = _bare_number(before.group(1)), _bare_number(after.group(1))
    if left is None or right is None:
        return False
    both_years = _BARE_YEAR.fullmatch(left) and (
        _BARE_YEAR.fullmatch(right) or _TWO_DIGIT_YEAR.fullmatch(right)
    )
    return not both_years


def find_non_ascii_date_ranges(text):
    """Return (line, dash) for every year joined to a non-ASCII dash in raw text.

    Works on the raw text layer, never on `normalize_text()` output: the fold
    maps U+2013 back to `-` so `required strings "2016-2024"` can match what the
    template renders, which is exactly why `required strings` cannot see this defect.
    A year on either side of the dash is enough ("Mar 2016 - Jul 2016",
    "2016 - Present"), so the check is locale-agnostic. A range whose two ends
    are both bare numbers is a date only when both are years: "EUR 600k-1M",
    "EUR 1500-2000" and "2000-5000 requests/s" are quantities and are left
    alone, while a numerically formatted date ("03/2016-07/2024", "2016-03-2024-07")
    is not a bare number on either side and is still caught.
    """
    hits = []
    for match in NON_ASCII_DATE_RANGE.finditer(text):
        dash = next(c for c in match.group(0) if c in NON_ASCII_DASHES)
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line_end = line_end if line_end != -1 else len(text)
        line = text[line_start:line_end]
        if _quantity_range(line, match.start() + match.group(0).index(dash) - line_start):
            continue
        hits.append((" ".join(line.split()), dash))
    return hits


def _extract_pypdf(pdf_path):
    """Return (text, pages) or None if pypdf is unavailable, raises, or yields no text."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(pdf_path))
        pages = len(reader.pages)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 (any pypdf failure falls back)
        return None
    # Harden: treat empty/degraded extraction as failure so we fall back
    if len(normalize_text(text)) == 0:
        return None
    return text, pages


def _extract_pdftotext(pdf_path):
    text = run_tool(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"])
    # pdftotext has no page count; pdfinfo ships in the same Poppler package.
    pages = parse_page_count(run_tool(["pdfinfo", str(pdf_path)]))
    return text, pages


def extract_text_layer(pdf_path):
    """Extract ATS-readable text. Returns (text, pages, extractor_name).

    Prefers Poppler `pdftotext` when it is installed, falling back to pypdf when
    it is absent, fails, or yields no text.
    """
    if shutil.which("pdftotext"):
        try:
            text, pages = _extract_pdftotext(pdf_path)
        except VerificationError:
            text = ""
        if normalize_text(text):
            return text, pages, "pdftotext"
    pypdf_result = _extract_pypdf(pdf_path)
    if pypdf_result is None:
        raise VerificationError("no usable text layer (install poppler-utils or pypdf)")
    text, pages = pypdf_result
    return text, pages, "pypdf"

"""Text folding shared by the privacy guard and the confidential-term audit."""
import re
import unicodedata

SEPARATORS = re.compile(r"[\s_-]+")


def fold(text: str) -> str:
    """Compatibility-normalised, case-folded text (full-width and ligature forms collapse)."""
    return unicodedata.normalize("NFKC", text).casefold()


def fold_accents(text: str) -> str:
    """Case-folded text with combining accents removed."""
    plain = unicodedata.normalize("NFKD", fold(text))
    return "".join(ch for ch in plain if not unicodedata.combining(ch))


def squash(text: str) -> str:
    """Folded text without whitespace, underscores or hyphens."""
    return SEPARATORS.sub("", fold(text))


def contains_term(text: str, term: str) -> bool:
    """True if term occurs in text, ignoring case and width.

    A term without separators also matches across them ("projectzebra" finds
    "Project Zebra"); a term that has its own separators keeps them significant
    ("acme-corp" does not find "AcmeCorp"), so a hyphenated slug or a ticket
    prefix like "ACME-" does not match a plain name.

    A match must start a word: the character before it is not a letter or digit,
    so "KIT-" finds "KIT-123" and "(KIT-12)" but not "toolkit-esr".
    """
    term = term.strip()
    if not term:
        return False
    folded = fold(text)
    if SEPARATORS.search(term):
        needle, starts = fold(term), list(range(len(folded)))
        haystack = folded
    else:
        needle = squash(term)
        starts = [i for i, ch in enumerate(folded) if not SEPARATORS.match(ch)]
        haystack = "".join(folded[i] for i in starts)
    word_start_needed = needle[:1].isalnum()
    at = haystack.find(needle)
    while at != -1:
        begin = starts[at]
        if not word_start_needed or begin == 0 or not folded[begin - 1].isalnum():
            return True
        at = haystack.find(needle, at + 1)
    return False


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(text).lower()).strip("-")


def file_part(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _ascii(text)).strip("_")


def split_name(name: str) -> tuple[str, str]:
    """First word and the rest, the split used for PDF file names and the kit."""
    first, _, last = name.strip().partition(" ")
    return first, last.strip()

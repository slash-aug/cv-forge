"""Text folding shared by the privacy guard and the confidential-term audit."""
import re
import unicodedata

SEPARATORS = re.compile(r"[\s_-]+")


def fold(text: str) -> str:
    """Compatibility-normalised, case-folded text (full-width and ligature forms collapse)."""
    return unicodedata.normalize("NFKC", text).casefold()


def squash(text: str) -> str:
    """Folded text without whitespace, underscores or hyphens."""
    return SEPARATORS.sub("", fold(text))


def contains_term(text: str, term: str) -> bool:
    """True if term occurs in text, ignoring case, width and separators."""
    needle = squash(term)
    return bool(needle) and needle in squash(text)

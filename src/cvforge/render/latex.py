"""LaTeX escaping, date formatting and the shared Jinja environment."""
from __future__ import annotations

import re
from importlib import resources
from typing import TYPE_CHECKING

from cvforge.profile.model import ProfileError

if TYPE_CHECKING:
    import jinja2

_ESCAPES = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    '"': r"\textquotedbl{}",
    "-": r"-\kern0pt",
}
# A hyphen is special only before another hyphen: TeX ligatures would turn "--" and
# "---" into en and em dashes, and a straight double quote into a curly one. LuaTeX
# ligatures ignore an empty group, so a zero kern separates the hyphens.
_SPECIAL = re.compile(r'[\\&%$#_{}~^"]|-(?=-)')
_URL_SPECIAL = re.compile(r"[%#]")

_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt-BR": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
    "pt-PT": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
}
_DATE = re.compile(r"(\d{4})(?:-(0[1-9]|1[0-2]))?")
_ONGOING = {"en": "Present", "pt-BR": "Atual", "pt-PT": "Presente"}


def escape_tex(s: str) -> str:
    """Escape LaTeX specials in one pass (so the backslash is handled first); non-ASCII is untouched."""
    return _SPECIAL.sub(
        lambda m: r"\textbackslash{}" if m.group() == "\\" else _ESCAPES[m.group()], s
    )


def escape_url(s: str) -> str:
    """Escape an \\href target: only % and # need it; ~ and _ must stay literal in the link."""
    return _URL_SPECIAL.sub(lambda m: "\\" + m.group(), s)


def format_date(value: str, lang: str, *, item_id: str = "date") -> str:
    """'YYYY-MM' becomes 'Mon YYYY' in the locale; a bare 'YYYY' stays as is."""
    match = _DATE.fullmatch(value)
    if not match:
        raise ProfileError(f"{item_id}: malformed date {value!r} (expected YYYY or YYYY-MM)")
    year, month = match.groups()
    return f"{_MONTHS[lang][int(month) - 1]} {year}" if month else year


def format_range(start: str, end: str | None, lang: str, *, item_id: str = "date") -> str:
    stop = _ONGOING[lang] if end is None else format_date(end, lang, item_id=item_id)
    return f"{format_date(start, lang, item_id=item_id)} - {stop}"


def jinja_env(package: str = "cvforge.render") -> jinja2.Environment:
    """Environment with LaTeX-safe delimiters; escaping is explicit via the |tex filter."""
    import jinja2  # imported here so the CLI starts without it

    templates = resources.files(package).joinpath("templates")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates)),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix="%%",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["tex"] = escape_tex
    env.filters["url"] = escape_url
    return env

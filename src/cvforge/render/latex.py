"""LaTeX escaping, date formatting and the shared Jinja environment."""
import re
from importlib import resources

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
}
_SPECIAL = re.compile(r"[\\&%$#_{}~^]")

_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "pt-BR": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    "pt-PT": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
}
_ONGOING = {"en": "Present", "pt-BR": "Atual", "pt-PT": "Presente"}


def escape_tex(s: str) -> str:
    """Escape LaTeX specials in one pass (so the backslash is handled first); non-ASCII is untouched."""
    return _SPECIAL.sub(
        lambda m: r"\textbackslash{}" if m.group() == "\\" else _ESCAPES[m.group()], s
    )


def format_date(value: str, lang: str) -> str:
    """'YYYY-MM' becomes 'Mon YYYY' in the locale; a bare 'YYYY' stays as is."""
    year, _, month = value.partition("-")
    return f"{_MONTHS[lang][int(month) - 1]} {year}" if month else year


def format_range(start: str, end: str | None, lang: str) -> str:
    stop = _ONGOING[lang] if end is None else format_date(end, lang)
    return f"{format_date(start, lang)} - {stop}"


def jinja_env(package: str = "cvforge.render") -> jinja2.Environment:
    """Environment with LaTeX-safe delimiters; escaping is explicit via the |tex filter."""
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
    return env

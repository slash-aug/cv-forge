"""Render the tailored cover letter to xelatex source using the upstream cover.cls."""
from datetime import date
from importlib import resources
from pathlib import Path

from cvforge.profile.model import ProfileError
from cvforge.render.contact import contact_links
from cvforge.render.latex import jinja_env

ASSETS_DIR = Path(str(resources.files("cvforge.render").joinpath("assets")))

_MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
    "pt-BR": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"],
}


_MONTHS["pt-PT"] = _MONTHS["pt-BR"]


def format_letter_date(day: date, lang: str) -> str:
    if lang not in _MONTHS:
        raise ProfileError(f"unsupported locale {lang!r} for the letter date")
    month = _MONTHS[lang][day.month - 1]
    if lang == "en":
        return f"{day.day} {month} {day.year}"
    return f"{day.day} de {month} de {day.year}"


def _header_links(basics: dict) -> list[dict]:
    """Phone, email and LinkedIn only (the CV also lists GitHub)."""
    return [l for l in contact_links(basics)
            if "github.com" not in l["text"]]


def letter_context(tailored: dict, master: dict, today: date | None = None) -> dict:
    """Every value the letter template prints, resolved and localised."""
    letter = tailored.get("letter")
    if not letter:
        raise ProfileError("tailored has no letter")
    basics = master["basics"]
    return {
        "name": basics["name"],
        "links": _header_links(basics),
        "date": format_letter_date(today or date.today(), tailored["lang"]),
        "letter": letter,
    }


def render_letter_context(context: dict) -> str:
    return jinja_env().get_template("cover.tex.j2").render(**context)


def render_letter(tailored: dict, master: dict, today: date | None = None) -> str:
    return render_letter_context(letter_context(tailored, master, today))

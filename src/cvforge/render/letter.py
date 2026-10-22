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
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"],
}


def format_letter_date(day: date, lang: str) -> str:
    if lang == "en":
        return f"{day.day} {_MONTHS['en'][day.month - 1]} {day.year}"
    return f"{day.day} de {_MONTHS['pt'][day.month - 1]} de {day.year}"


def render_letter(tailored: dict, master: dict, today: date | None = None) -> str:
    letter = tailored.get("letter")
    if not letter:
        raise ProfileError("tailored has no letter")
    basics = master["basics"]
    return jinja_env().get_template("cover.tex.j2").render(
        name=basics["name"],
        links=contact_links(basics),
        date=format_letter_date(today or date.today(), tailored["lang"]),
        letter=letter,
    )

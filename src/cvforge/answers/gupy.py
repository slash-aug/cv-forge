"""The optional "Apresente-se" step every Gupy application form shows."""
from __future__ import annotations

from pathlib import Path

from cvforge.profile.model import read_yaml

GUPY_QUESTIONS = (
    {"question": "A empresa deseja saber mais sobre você! Fale sobre você e sua trajetória "
                 "profissional, contando como pode ajudar a empresa no desafio descrito na vaga.",
     "hint": "limit 1500, tailor to this posting"},
    {"question": "Quais são as suas habilidades mais valiosas para esta vaga?",
     "hint": "pick up to 3 from the Gupy skills, comma separated"},
)


def gupy_skills(path: Path) -> list[str]:
    """Skills on the candidate's Gupy profile (data/answers/gupy.yaml), the only ones the form offers."""
    if not Path(path).exists():
        return []
    data = read_yaml(Path(path), "gupy skills") or {}
    return [str(s) for s in data.get("skills") or []]

from datetime import date
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.render.letter import ASSETS_DIR, render_letter
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")
TODAY = date(2026, 10, 21)


def test_letter_structure_and_escaping():
    out = render_letter(T, M, today=TODAY)
    assert r"\documentclass[]{cover}" in out
    assert "Dear Hiring Team," in out
    for p in T["letter"]["paragraphs"]:
        assert p.replace("%", r"\%") in out
    assert r"40\% " in out


def test_letter_header_closing_and_date():
    out = render_letter(T, M, today=TODAY)
    assert "Ana Exemplo" in out
    assert r"\href{mailto:ana.exemplo@example.com}" in out
    assert "linkedin.com/in/ana-exemplo" in out
    assert "21 October 2026" in out
    assert r"\closing{Kind regards,}" in out
    assert r"\signature{Ana Exemplo}" in out


@pytest.mark.parametrize("lang", ["pt-BR", "pt-PT"])
def test_letter_date_portuguese(lang):
    out = render_letter({**T, "lang": lang}, M, today=TODAY)
    assert "21 de outubro de 2026" in out


def test_letter_default_date_is_today():
    assert f"{date.today().year}" in render_letter(T, M)


def test_letter_has_no_danish():
    assert "venlig" not in render_letter(T, M, today=TODAY).lower()


def test_letter_special_chars_escaped():
    t = {**T, "letter": {**T["letter"], "paragraphs": ["Integração & testes #1 a_b"]}}
    assert r"Integração \& testes \#1 a\_b" in render_letter(t, M, today=TODAY)


def test_letter_missing_raises():
    t = {k: v for k, v in T.items() if k != "letter"}
    with pytest.raises(ProfileError, match="tailored has no letter"):
        render_letter(t, M)


def test_assets_present():
    assert (ASSETS_DIR / "cover.cls").read_text().startswith("% Ported from ai-job-search (MIT)")
    assert (ASSETS_DIR / "OpenFonts" / "fonts" / "raleway" / "Raleway-Medium.otf").exists()
    assert (ASSETS_DIR / "OpenFonts" / "fonts" / "lato" / "Lato-Lig.ttf").exists()

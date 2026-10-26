from datetime import date
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.render.letter import ASSETS_DIR, format_letter_date, render_letter
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
        p = p if isinstance(p, str) else p["text"]
        assert p.replace("%", r"\%") in out
    assert r"40\% " in out


def test_letter_header_closing_and_date():
    out = render_letter(T, M, today=TODAY)
    assert "Ana Exemplo" in out
    assert r"\href{mailto:ana.exemplo@example.com}" in out
    assert "linkedin.com/in/ana-exemplo" in out
    assert "github.com" not in out
    assert r"\mbox{" in out
    assert "21 October 2026" in out
    assert r"\closing{Kind regards,}" in out
    assert r"\signature{Ana Exemplo}" in out


@pytest.mark.parametrize("lang", ["pt-BR", "pt-PT"])
def test_letter_date_portuguese(lang):
    out = render_letter({**T, "lang": lang}, M, today=TODAY)
    assert "21 de outubro de 2026" in out


def test_letter_default_date_is_today():
    assert format_letter_date(date.today(), "en") in render_letter(T, M)


def test_letter_has_no_danish():
    assert "venlig" not in render_letter(T, M, today=TODAY).lower()


def test_letter_special_chars_escaped():
    t = {**T, "letter": {**T["letter"], "paragraphs": ["Integração & testes #1 a_b"]}}
    assert r"Integração \& testes \#1 a\_b" in render_letter(t, M, today=TODAY)


def test_letter_href_target_keeps_tilde():
    master = {**M, "basics": {**M["basics"], "profiles": [
        {"network": "LinkedIn", "url": "https://linkedin.com/in/~ana"}]}}
    assert r"\href{https://linkedin.com/in/~ana}" in render_letter(T, master, today=TODAY)


def test_letter_missing_raises():
    t = {k: v for k, v in T.items() if k != "letter"}
    with pytest.raises(ProfileError, match="tailored has no letter"):
        render_letter(t, M)


def test_assets_present():
    assert (ASSETS_DIR / "cover.cls").read_text().startswith("% Ported from ai-job-search (MIT)")
    assert (ASSETS_DIR / "OpenFonts" / "fonts" / "raleway" / "Raleway-Medium.otf").exists()
    assert (ASSETS_DIR / "OpenFonts" / "fonts" / "lato" / "Lato-Lig.ttf").exists()


def test_unknown_locale_raises():
    with pytest.raises(ProfileError, match="fr"):
        render_letter({**T, "lang": "fr"}, M, today=TODAY)


@pytest.mark.parametrize("font", ["lato", "raleway"])
def test_ofl_licence_shipped(font):
    text = (ASSETS_DIR / "OpenFonts" / "fonts" / font / "OFL.txt").read_text()
    assert "SIL OPEN FONT LICENSE Version 1.1" in text


def test_dict_paragraph_renders():
    paragraph = {"text": "Grew sales by 40%.", "refs": ["h-load-time"]}
    t = {**T, "letter": {**T["letter"], "paragraphs": [paragraph]}}
    out = render_letter(t, M, today=TODAY)
    assert r"Grew sales by 40\%." in out
    assert "refs" not in out


CV_FONTS = {"Lato-Reg.ttf", "Lato-Bol.ttf", "Lato-RegIta.ttf", "Lato-BolIta.ttf"}


def test_cover_class_uses_only_the_cv_fonts():
    import re

    cls = (ASSETS_DIR / "cover.cls").read_text()
    assert "Raleway" not in cls
    used = set(re.findall(r"Lato-[A-Za-z]+", cls))
    assert used and {f"{u}.ttf" for u in used} <= CV_FONTS, used


def test_letter_paragraphs_are_justified_without_hyphenation():
    cls = (ASSETS_DIR / "cover.cls").read_text()
    body = next(line for line in cls.splitlines() if line.startswith(r"\newcommand{\lettercontent}"))
    assert r"\justifying" in body and r"\raggedright" not in body
    assert r"\hyphenpenalty=10000" in cls
    assert r"\setlength{\JustifyingParindent}{0pt}" in cls  # no first-line indent, like the CV


@pytest.mark.latex
def test_compiled_letter_matches_cv_fonts_and_keeps_words_whole(cfg):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.xelatex:
        pytest.skip("no xelatex engine")
    long = ("Integrated payment gateways, concurrency-safe wallets, webhooks and TypeORM transactions "
            "across PostgreSQL databases with comprehensive automated testing infrastructure. ") * 6
    t = {**T, "letter": {**T["letter"], "paragraphs": [long]}}
    pdf = compile_tex(render_letter(t, M, today=TODAY), engine=cfg.xelatex,
                      build_dir=cfg.build_dir / "test", jobname="letter_fonts", assets=ASSETS_DIR)
    names = set()
    for page in PdfReader(pdf).pages:
        for font in (page["/Resources"].get("/Font") or {}).values():
            names.add(str(font.get_object()["/BaseFont"]).split("+")[-1])
    assert names and names <= {"Lato-Regular", "Lato-Bold", "Lato-Italic", "Lato-BoldItalic"}, names
    text = PdfReader(pdf).pages[0].extract_text()
    assert not any(line.rstrip().endswith("-") for line in text.splitlines()), text


def test_letter_spacing_is_even_and_single_spaced_after_periods():
    cls = (ASSETS_DIR / "cover.cls").read_text()

    def command(name):
        return next(line for line in cls.splitlines() if line.startswith(rf"\newcommand{{\{name}}}"))

    # Blocks end with \par plus one fixed gap, never stacked empty lines.
    for name in ("companyname", "lettercontent", "closing"):
        body = command(name)
        assert r"\mbox{}\\" not in body, name
        assert r"\par\vspace{" in body, name
    assert r"\frenchspacing" in cls  # one space after a period, like the CV

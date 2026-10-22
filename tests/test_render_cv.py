import copy
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.render.cv import build_cv_view, render_cv
from cvforge.render.latex import escape_tex, format_range, jinja_env
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")
EM_DASH = "—"


def test_escape():
    assert escape_tex("A & B 100% #1 a_b") == r"A \& B 100\% \#1 a\_b"


def test_escape_all_specials():
    assert escape_tex("$ { } ~ ^") == r"\$ \{ \} \textasciitilde{} \textasciicircum{}"


def test_escape_backslash_first():
    assert escape_tex(r"a\b&") == r"a\textbackslash{}b\&"


def test_escape_keeps_accents():
    assert escape_tex("Integração") == "Integração"


def test_range_ongoing():
    assert format_range("2026-06", None, "en") == "Jun 2026 - Present"
    assert format_range("2026-06", None, "pt-BR") == "jun 2026 - Atual"
    assert format_range("2026-06", None, "pt-PT") == "jun 2026 - Presente"
    assert format_range("2025-08", "2026-02", "pt-PT") == "ago 2025 - fev 2026"


def test_jinja_env_delimiters_and_filter():
    out = jinja_env().from_string(r"%% for x in xs" "\n" r"\VAR{x | tex}" "\n" "%% endfor\n").render(xs=["a&b"])
    assert out.strip() == r"a\&b"


def test_render_contains_bullets_and_name():
    tex = render_cv(T, M)
    assert r"\name{Ana}{Exemplo}" in tex
    assert r"Integração de pagamentos \& reconciliação" in tex
    assert r"Cut load time by 40\% by reworking" in tex
    assert r"\email{ana.exemplo@example.com}" in tex
    assert r"\social[github]{ana-exemplo}" in tex
    assert r"\social[linkedin]{ana-exemplo}" in tex
    assert "Ported from ai-job-search (MIT): cv/main_example.tex" in tex
    assert EM_DASH not in tex


def test_render_section_order_and_headings():
    tex = render_cv(T, M)
    heads = ["Summary", "Experience", "Skills", "Education", "Certifications", "Languages"]
    positions = [tex.index(rf"\section{{{h}}}") for h in heads]
    assert positions == sorted(positions)


def test_positions_newest_first_and_employer_order():
    tex = render_cv(T, M)
    order = ["Jun 2024 - Present", "Mar 2022 - May 2024", "Jan 2020 - Feb 2022"]
    idx = [tex.index(d) for d in order]
    assert idx == sorted(idx)


def test_international_and_remote_location():
    tex = render_cv(T, M)
    assert r"{Remote (International remote freelance)}" in tex
    pt = render_cv({**T, "lang": "pt-BR"}, M)
    assert "(Freelance internacional remoto)" in pt
    assert "Experiência Profissional" in pt


def test_pt_pt_headings_and_ongoing():
    tex = render_cv({**T, "lang": "pt-PT"}, M)
    assert r"\section{Línguas}" in tex
    assert "Jun 2024".lower() in tex and "Presente" in tex


def test_view_is_separable():
    view = build_cv_view(T, M)
    assert view["contact"]["first"] == "Ana" and view["contact"]["last"] == "Exemplo"
    assert view["experience"][0]["dates"] == "Jun 2024 - Present"


def test_missing_locale_raises_naming_id():
    master = copy.deepcopy(M)
    pos = master["work"][1]["positions"][0]
    pos["title"] = {"en": "Senior Engineer"}
    with pytest.raises(ProfileError, match="p-sampleworks-eng.*pt-PT"):
        render_cv({**T, "lang": "pt-PT"}, master)


def test_certificate_locale_restriction_raises():
    tailored = {**T, "lang": "pt-PT", "certificates": ["cert-agile"]}
    with pytest.raises(ProfileError, match="cert-agile"):
        render_cv(tailored, M)

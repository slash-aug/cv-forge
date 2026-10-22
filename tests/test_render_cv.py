import copy
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.render.cv import build_cv_view, render_cv
from cvforge.render.latex import (
    escape_tex,
    escape_url,
    format_date,
    format_range,
    jinja_env,
)
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")
EM_DASH = chr(0x2014)


def test_escape():
    assert escape_tex("A & B 100% #1 a_b") == r"A \& B 100\% \#1 a\_b"


def test_escape_all_specials():
    assert escape_tex("$ { } ~ ^") == r"\$ \{ \} \textasciitilde{} \textasciicircum{}"


def test_escape_backslash_first():
    assert escape_tex(r"a\b&") == r"a\textbackslash{}b\&"


def test_escape_keeps_accents():
    assert escape_tex("Integração") == "Integração"


def test_escape_breaks_dash_ligatures():
    assert escape_tex("a -- b --- c") == r"a -\kern0pt- b -\kern0pt-\kern0pt- c"


def test_escape_keeps_straight_double_quote():
    assert escape_tex('say "hi"') == r"say \textquotedbl{}hi\textquotedbl{}"


def test_escape_url_only_percent_and_hash():
    assert escape_url("https://x.example/~ana/a_b?q=1%20#top") == r"https://x.example/~ana/a_b?q=1\%20\#top"


def test_href_target_keeps_tilde():
    master = copy.deepcopy(M)
    master["basics"]["profiles"] = [{"network": "Site", "url": "https://example.com/~ana"}]
    tex = render_cv(T, master)
    assert r"\href{https://example.com/~ana}{example.com/\textasciitilde{}ana}" in tex


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
    assert r"\href{mailto:ana.exemplo@example.com}{ana.exemplo@example.com}" in tex
    assert r"\href{https://github.com/ana-exemplo}{github.com/ana-exemplo}" in tex
    assert r"\href{https://www.linkedin.com/in/ana-exemplo}{linkedin.com/in/ana-exemplo}" in tex
    assert "\\social" not in tex and "\\phone" not in tex and "\\email" not in tex
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


def test_international_location_is_not_prefixed_with_remote():
    tex = render_cv(T, M)
    assert r"{International remote freelance}" in tex
    assert "Remote (International" not in tex


def test_international_location_localized():
    pt = render_cv({**T, "lang": "pt-BR"}, M)
    assert "{Freelance internacional remoto}" in pt
    assert "Experiência Profissional" in pt


def test_language_fluency_localized():
    master = copy.deepcopy(M)
    master["languages"][0]["fluency"] = {"en": "Native", "pt-BR": "Nativo", "pt-PT": "Nativo"}
    langs = build_cv_view({**T, "lang": "pt-BR"}, master)["languages"]
    assert {"name": "Português", "detail": "Nativo"} in langs


def test_language_fluency_missing_locale_names_item():
    master = copy.deepcopy(M)
    master["languages"][0]["fluency"] = {"en": "Native"}
    with pytest.raises(ProfileError, match="lang-pt.*pt-BR"):
        build_cv_view({**T, "lang": "pt-BR"}, master)


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


def test_certificate_excluded_by_locale_is_skipped():
    tailored = {**T, "lang": "pt-PT", "certificates": ["cert-agile", "cert-cloud"]}
    tex = render_cv(tailored, M)
    assert "Example Agile Foundations" not in tex
    assert "Example Cloud Practitioner" in tex


def test_certificate_included_when_locale_listed():
    tex = render_cv({**T, "certificates": ["cert-agile"]}, M)
    assert "Example Agile Foundations" in tex


def test_preamble_no_icons_and_plain_bullets():
    tex = render_cv(T, M)
    assert r"\moderncvicons{letters}" in tex
    assert r"\renewcommand{\labelitemi}{\textbullet}" in tex
    assert tex.index(r"\moderncvstyle{banking}") < tex.index(r"\renewcommand{\labelitemi}")


def test_empty_bullets_have_no_itemize():
    tailored = copy.deepcopy(T)
    tailored["experience"][0]["positions"][0]["bullets"] = []
    tex = render_cv(tailored, M)
    assert tex.count(r"\begin{itemize}") == 2 and tex.count(r"\end{itemize}") == 2


def test_format_date_malformed_names_item():
    with pytest.raises(ProfileError, match="p-x.*2024-13"):
        format_date("2024-13", "en", item_id="p-x")
    with pytest.raises(ProfileError, match="p-x"):
        format_date("junk", "en", item_id="p-x")


def test_master_company_name_is_escaped():
    master = copy.deepcopy(M)
    master["work"][1]["name"] = "A&B 100% x_y"
    assert r"{A\&B 100\% x\_y}" in render_cv(T, master)


def test_profiles_are_visible_urls_without_scheme_or_www():
    master = copy.deepcopy(M)
    master["basics"]["profiles"] = [
        {"network": "LinkedIn", "url": "https://uk.linkedin.com/in/ana-exemplo/"},
        {"network": "Site", "url": "http://www.ana.example.com/me_x"},
    ]
    tex = render_cv(T, master)
    assert r"\href{https://uk.linkedin.com/in/ana-exemplo}{uk.linkedin.com/in/ana-exemplo}" in tex
    assert r"{ana.example.com/me\_x}" in tex


@pytest.mark.latex
def test_compiled_text_layer_is_ats_clean(cfg):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    pdf = compile_tex(render_cv(T, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_ats")
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    for token in ("GITHUB", "LINKEDIN", "MOBILE", chr(0x1F7E4)):
        assert token not in text
    assert "Integração de pagamentos & reconciliação" in text
    assert "Jun 2024 - Present" in text
    assert "github.com/ana-exemplo" in text
    assert "linkedin.com/in/ana-exemplo" in text
    assert "ana.exemplo@example.com" in text and "+351 900 000 000" in text
    assert chr(0x2022) in text

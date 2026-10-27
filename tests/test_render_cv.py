import copy
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.render.cv import build_cv_view, render_cv, render_view
from cvforge.render.latex import (
    escape_tex,
    escape_url,
    format_date,
    format_range,
    jinja_env,
)
from cvforge.render.letter import ASSETS_DIR
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")
T_PT = load_tailored(PERSONA / "tailored.pt-BR.yaml")
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
    assert format_range("2026-06", None, "pt-BR") == "Jun 2026 - Atual"
    assert format_range("2026-06", None, "pt-PT") == "Jun 2026 - Presente"
    assert format_range("2025-08", "2026-02", "pt-PT") == "Ago 2025 - Fev 2026"


def test_jinja_env_delimiters_and_filter():
    out = jinja_env().from_string(r"%% for x in xs" "\n" r"\VAR{x | tex}" "\n" "%% endfor\n").render(xs=["a&b"])
    assert out.strip() == r"a\&b"


def test_render_contains_bullets_and_name():
    tex = render_cv(T, M)
    assert r"\name{Ana}{Exemplo}" in tex
    assert r"Payment integration \& reconciliation" in tex
    assert r"Cut load time by 40\% by reworking" in tex
    assert r"\href{mailto:ana.exemplo@example.com}{ana.exemplo@example.com}" in tex
    assert r"\href{https://github.com/ana-exemplo}{github.com/ana-exemplo}" in tex
    assert r"\href{https://www.linkedin.com/in/ana-exemplo}{linkedin.com/in/ana-exemplo}" in tex
    assert "\\social" not in tex and "\\phone" not in tex and "\\email" not in tex
    assert "Ported from ai-job-search (MIT): cv/main_example.tex" in tex
    assert EM_DASH not in tex


def test_pt_br_persona_keeps_accents_and_escapes():
    tex = render_cv(T_PT, M)
    assert r"Integração de pagamentos \& reconciliação" in tex
    assert r"\section{Experiência Profissional}" in tex
    assert "Nativo" in tex


def test_en_persona_bullets_are_english():
    bullets = [b["text"] for w in T["experience"] for p in w["positions"] for b in p["bullets"]]
    assert all(b.isascii() for b in bullets), bullets


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
    assert "Jun 2024 - Presente" in tex


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


def test_certificate_omits_issuer_already_in_name():
    master = copy.deepcopy(M)
    certs = master["certificates"]
    base = next(c for c in certs if c["id"] == "cert-agile")
    certs.append({**base, "id": "cert-dup", "name": "Acme Test Certificate (90/100)", "issuer": "ACME test"})
    certs.append({**base, "id": "cert-other", "name": "Plain Certificate", "issuer": "Other Body"})
    tex = render_cv({**T, "certificates": ["cert-dup", "cert-other"]}, master)
    assert r"Acme Test Certificate (90/100)}" in tex
    assert "ACME test" not in tex
    assert "Plain Certificate, Other Body" in tex


def test_certificate_keeps_short_issuer_inside_another_word():
    master = copy.deepcopy(M)
    base = next(c for c in master["certificates"] if c["id"] == "cert-agile")
    master["certificates"].append({**base, "id": "cert-w", "name": "Laws Practitioner", "issuer": "AWS"})
    tex = render_cv({**T, "certificates": ["cert-w"]}, master)
    assert "Laws Practitioner, AWS" in tex


def test_preamble_no_icons_and_plain_bullets():
    tex = render_cv(T, M)
    assert r"\moderncvicons{letters}" in tex
    assert r"\renewcommand{\labelitemi}{\textbullet}" in tex
    assert tex.index(r"\moderncvstyle{banking}") < tex.index(r"\renewcommand{\labelitemi}")


def test_empty_bullets_have_no_itemize():
    tailored = copy.deepcopy(T)
    tailored["experience"][0]["positions"][0]["bullets"] = []
    tex = render_cv(tailored, M)
    assert tex.count(r"\begin{cvbullets}") == 2 and tex.count(r"\end{cvbullets}") == 2


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


def _compiled_text(cfg, tailored, jobname):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    pdf = compile_tex(render_cv(tailored, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname=jobname, assets=ASSETS_DIR)
    return "\n".join(p.extract_text() for p in PdfReader(pdf).pages)


@pytest.mark.latex
def test_compiled_text_layer_is_ats_clean(cfg):
    text = _compiled_text(cfg, T, "cv_ats")
    for token in ("GITHUB", "LINKEDIN", "MOBILE", chr(0x1F7E4)):
        assert token not in text
    assert "Payment integration & reconciliation" in text
    assert "Jun 2024 - Present" in text
    assert "github.com/ana-exemplo" in text
    assert "linkedin.com/in/ana-exemplo" in text
    assert "ana.exemplo@example.com" in text and "+351 900 000 000" in text
    assert chr(0x2022) in text


@pytest.mark.latex
def test_compiled_pt_br_text_layer_keeps_accents(cfg):
    text = _compiled_text(cfg, T_PT, "cv_ats_pt")
    assert "Integração de pagamentos & reconciliação" in text
    assert "Jun 2024 - Atual" in text


@pytest.mark.latex
def test_compiled_cv_is_set_in_lato(cfg):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    pdf = compile_tex(render_cv(T, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_fonts", assets=ASSETS_DIR)
    names = set()
    for page in PdfReader(pdf).pages:
        for font in (page["/Resources"].get("/Font") or {}).values():
            names.add(str(font.get_object()["/BaseFont"]))
    assert any("Lato" in n for n in names), names
    assert not any("LMSans" in n or "LMRoman" in n for n in names), names


@pytest.mark.latex
def test_title_is_on_its_own_line_under_the_name(cfg):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    pdf = compile_tex(render_cv(T, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_title", assets=ASSETS_DIR)
    text = PdfReader(pdf).pages[0].extract_text()
    lines = [ln.strip() for ln in text.splitlines()]
    basics = M["basics"]
    name = f"{basics['name'].split()[0]} {basics['name'].split()[-1]}"
    title = basics["label"]["en"]
    assert name in lines, lines[:6]
    assert title in lines, lines[:6]
    assert lines.index(title) == lines.index(name) + 1
    assert not any(ln.startswith("|") for ln in lines)  # no separator before the title


def _header_lines(pdf):
    import re
    import subprocess

    xml = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-bbox-layout", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    width = float(re.search(r'<page width="([\d.]+)"', xml).group(1))
    lines = []
    for m in re.finditer(r"<line xMin=\"([\d.]+)\" yMin=\"[\d.]+\" xMax=\"([\d.]+)\" yMax=\"[\d.]+\">(.*?)</line>",
                         xml, re.DOTALL):
        words = re.findall(r">([^<]+)</word>", m.group(3))
        lines.append((float(m.group(1)), float(m.group(2)), " ".join(words)))
    return width, lines


@pytest.mark.latex
def test_long_name_and_title_stay_centered_inside_margins(cfg):
    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    master = copy.deepcopy(M)
    master["basics"]["name"] = "Maria Fernanda de Oliveira Santos"
    master["basics"]["label"] = {
        lang: "Senior Full Stack Developer | Team Lead | Mentor" for lang in ("en", "pt-BR", "pt-PT")}
    pdf = compile_tex(render_cv(T, master), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_long_header", assets=ASSETS_DIR)
    width, lines = _header_lines(pdf)
    texts = [t for _, _, t in lines]
    assert "Maria Fernanda de Oliveira Santos" in texts  # one line, not wrapped
    summary = next(i for i, t in enumerate(texts) if t == "Summary")
    header = lines[:summary]
    margin = width * 0.1
    title_words = " ".join(t for _, _, t in header[1:]).replace("|", " ")
    for part in ("Senior Full Stack Developer", "Team Lead", "Mentor"):
        assert part in " ".join(title_words.split()), part
    for x0, x1, t in header:
        assert x0 >= margin - 2 and x1 <= width - margin + 2, (t, x0, x1)
        assert abs(x0 - (width - x1)) <= 4, (t, x0, width - x1)


@pytest.mark.latex
def test_title_is_clearly_smaller_than_the_name(cfg):
    import re
    import subprocess

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    pdf = compile_tex(render_cv(T, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_title_size", assets=ASSETS_DIR)
    xml = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-bbox", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    heights = {}
    for y0, y1, w in re.findall(r'yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">([^<]+)<', xml):
        heights.setdefault(w, float(y1) - float(y0))  # first occurrence is the header
    assert heights["Full-stack"] < 0.7 * heights["Exemplo"]


def test_cv_turns_hyphenation_off():
    tex = render_cv(T, M)
    preamble = tex[:tex.index(r"\begin{document}")]
    assert r"\hyphenpenalty=10000" in preamble and r"\exhyphenpenalty=10000" in preamble


@pytest.mark.latex
def test_compiled_cv_keeps_words_whole(cfg):
    from pypdf import PdfReader

    from cvforge.build import compile_tex

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    t = copy.deepcopy(T)
    t["experience"][0]["positions"][0]["bullets"][0]["text"] = (
        "Structured the Steam Web API integration with TypeORM transactions, PostgreSQL databases, "
        "concurrency-safe wallets and comprehensive automated testing infrastructure. ") * 4
    pdf = compile_tex(render_cv(t, M), engine=cfg.lualatex,
                      build_dir=cfg.build_dir / "test", jobname="cv_hyphen", assets=ASSETS_DIR)
    text = "\n".join(page.extract_text() for page in PdfReader(pdf).pages)
    broken = [ln for ln in map(str.rstrip, text.splitlines()) if ln.endswith("-") and ln[-2:-1].isalpha()]
    assert not broken, broken


def _ie_master(**rights):
    master = copy.deepcopy(M)
    prefs = master["x-preferences"]
    prefs["relocation"] = True
    prefs["workRights"] = {"BR": {"status": "citizen"}, "PT": {"status": "mobility"},
                           "IE": {"status": "needs-permit", "degreeRecognised": "unknown",
                                  "soc": ["2136"], **rights}}
    return master


IE_BLOCK = {"route": "csep-if-degree", "soc": "2136", "on_csol": True, "salary_eur_year": 55000.0,
            "permit_record": None, "lmnt": False, "sponsorship_silent": True}


def test_no_region_view_identical_to_today():
    assert build_cv_view(T, M, None) == build_cv_view(T, M)
    assert render_view(build_cv_view(T, M, None)) == render_cv(T, M)
    assert "References" not in render_cv(T, M)


def test_ie_region_header_line_and_label():
    from cvforge.render.irish import ireland_region

    master = _ie_master()
    region = ireland_region(master, city="Cork", ireland=IE_BLOCK)
    assert region.permit_line == "Requires employment permit (Critical Skills occupation)"
    assert region.location_label == "Relocating to Cork, Ireland"
    view = build_cv_view(T, master, region)
    assert view["contact"]["address"] == "Relocating to Cork, Ireland"
    tex = render_view(view)
    assert r"\address{Relocating to Cork, Ireland}{}{}" in tex
    head = tex.index(r"\patchcmd{\makehead}{\titlestyle{~|~\@title}}")
    assert tex.index("Requires employment permit (Critical Skills occupation)", head) < tex.index(r"\extrainfo{")


def test_ie_region_label_without_city_or_relocation():
    from cvforge.render.irish import ireland_region

    master = _ie_master()
    assert ireland_region(master, city=None, ireland=IE_BLOCK).location_label == "Relocating to Ireland"
    master["x-preferences"]["relocation"] = False
    region = ireland_region(master, city="Cork", ireland=IE_BLOCK)
    assert region.location_label is None
    assert build_cv_view(T, master, region)["contact"]["address"] == build_cv_view(T, M)["contact"]["address"]


def test_ie_region_csep_route_line():
    from cvforge.render.irish import ireland_region

    region = ireland_region(_ie_master(), city="Dublin", ireland={**IE_BLOCK, "route": "csep"})
    assert region.permit_line == "Eligible for Critical Skills Employment Permit (SOC 2136)"
    assert "Eligible for Critical Skills Employment Permit (SOC 2136)" in render_view(
        build_cv_view(T, _ie_master(), region))


def test_ie_region_degree_yes_line_and_off_list_line():
    from cvforge.render.irish import ireland_region

    yes = ireland_region(_ie_master(degreeRecognised="yes"), city=None, ireland=None)
    assert yes.permit_line == "Eligible for Critical Skills Employment Permit (SOC 2136)"
    off = ireland_region(_ie_master(), city=None,
                         ireland={**IE_BLOCK, "soc": "3131", "on_csol": False, "route": "gep"})
    assert off.permit_line == "Requires employment permit sponsorship"
    # no verdict: the CSOL comes from the permit table
    assert ireland_region(_ie_master(), city=None, ireland=None).permit_line == \
        "Requires employment permit (Critical Skills occupation)"


def test_ie_region_never_claims_csep_when_gep_route():
    from cvforge.render.irish import ireland_region

    region = ireland_region(_ie_master(degreeRecognised="yes"), city=None,
                            ireland={**IE_BLOCK, "route": "gep", "salary_eur_year": 38000.0})
    assert "Eligible" not in region.permit_line


def test_ie_region_without_ie_work_rights_has_no_permit_line():
    from cvforge.render.irish import ireland_region

    region = ireland_region(M, city="Cork", ireland=IE_BLOCK)
    assert region.permit_line == ""
    assert "employment permit" not in render_view(build_cv_view(T, M, region))


def test_references_line_ie_only():
    from cvforge.render.irish import ireland_region

    assert "References available on request" not in render_cv(T, M)
    master = _ie_master()
    tex = render_view(build_cv_view(T, master, ireland_region(master, city=None, ireland=IE_BLOCK)))
    assert "References available on request" in tex
    assert tex.index("References available on request") > tex.index(r"\section{Languages}")
    assert tex.index("References available on request") < tex.index(r"\end{document}")


def test_ie_region_spelling_on_summary_and_bullets_only():
    from cvforge.render.irish import ireland_region

    master = _ie_master()
    tailored = copy.deepcopy(T)
    tailored["summary"]["text"] = "I optimized the color pipeline."
    tailored["experience"][0]["positions"][0]["bullets"][0]["text"] = "Organized the center."
    view = build_cv_view(tailored, master, ireland_region(master, city=None, ireland=IE_BLOCK))
    assert view["summary"] == "I optimised the colour pipeline."
    assert "Organised the centre." in view["experience"][0]["bullets"]
    plain = build_cv_view(tailored, M)
    assert plain["summary"] == "I optimized the color pipeline."
    pt = build_cv_view({**tailored, "lang": "pt-BR", "summary": {"text": "color"}}, master,
                       ireland_region(master, city=None, ireland=IE_BLOCK))
    assert pt["summary"] == "color"


def _stub_build(monkeypatch, tmp_path):
    from cvforge import cli
    from cvforge.checks.ats import AtsReport

    views = []
    monkeypatch.setattr(cli, "load_config", lambda: cli.Config(tmp_path, tmp_path, "lua", "xe"))
    monkeypatch.setattr(cli, "compile_tex", lambda *a, **k: tmp_path / "x.pdf")
    monkeypatch.setattr(cli, "_publish", lambda pdf, out, name: out / name)
    monkeypatch.setattr(cli, "ats_check", lambda pdf, **k: AtsReport(True, [], "", 1, "stub"))
    real = cli.render_view
    monkeypatch.setattr(cli, "render_view", lambda view: views.append(view) or real(view))
    return views


def _app(tmp_path, name, *, countries, quote, verdict=None):
    import json

    import yaml

    app = tmp_path / name
    app.mkdir()
    (app / "tailored.yaml").write_text((PERSONA / "tailored.yaml").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    req = yaml.safe_load((PERSONA / "requirements.yaml").read_text(encoding="utf-8"))
    req["location"] = {"workplace": "hybrid", "job_countries": countries, "allowed": [],
                       "quote": quote}
    (app / "requirements.yaml").write_text(yaml.safe_dump(req), encoding="utf-8")
    if verdict is not None:
        (app / "verdict.json").write_text(json.dumps({"verdict": "pass", "ireland": verdict}),
                                          encoding="utf-8")
    return app / "tailored.yaml"


def test_build_defaults_region_from_requirements(tmp_path, monkeypatch):
    import yaml

    from cvforge.cli import main

    views = _stub_build(monkeypatch, tmp_path)
    master = tmp_path / "master.yaml"
    master.write_text(yaml.safe_dump(_ie_master(), allow_unicode=True), encoding="utf-8")
    m = str(master)

    br = _app(tmp_path, "br", countries=["Brazil"], quote="Hybrid in Sao Paulo, Brazil.")
    assert main(["build", str(br), "--master", m, "--no-letter"]) == 0
    assert views[-1] == build_cv_view(T, _ie_master())

    ie = _app(tmp_path, "ie", countries=["Ireland"], quote="Hybrid, 3 days a week in our Cork office.",
              verdict={**IE_BLOCK, "route": "csep"})
    assert main(["build", str(ie), "--master", m, "--no-letter"]) == 0
    assert views[-1]["contact"]["address"] == "Relocating to Cork, Ireland"
    assert views[-1]["contact"]["permit_line"] == \
        "Eligible for Critical Skills Employment Permit (SOC 2136)"

    assert main(["build", str(ie), "--master", m, "--no-letter", "--region", "none"]) == 0
    assert views[-1] == build_cv_view(T, _ie_master())

    no_city = _app(tmp_path, "ie2", countries=["Ireland"], quote="Remote within Ireland.")
    assert main(["build", str(no_city), "--master", m, "--no-letter"]) == 0
    assert views[-1]["contact"]["address"] == "Relocating to Ireland"
    assert views[-1]["contact"]["permit_line"] == \
        "Requires employment permit (Critical Skills occupation)"

    assert main(["master-cv", m, "--lang", "en", "--out", str(tmp_path)]) == 0
    assert "permit_line" not in views[-1]["contact"]
    assert main(["master-cv", m, "--lang", "en", "--out", str(tmp_path), "--region", "IE"]) == 0
    assert views[-1]["contact"]["address"] == "Relocating to Ireland"


@pytest.mark.latex
def test_compiled_ie_region_cv_passes_ats(cfg, tmp_path, monkeypatch):
    import yaml
    from pypdf import PdfReader

    from cvforge import cli

    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    reports = []
    real = cli.ats_check
    monkeypatch.setattr(cli, "ats_check", lambda pdf, **k: reports.append(real(pdf, **k)) or reports[-1])
    master = tmp_path / "master.yaml"
    master.write_text(yaml.safe_dump(_ie_master(), allow_unicode=True), encoding="utf-8")
    app = tmp_path / "app"
    app.mkdir()
    (app / "tailored.yaml").write_text((PERSONA / "tailored.yaml").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    assert cli.main(["build", str(app / "tailored.yaml"), "--master", str(master), "--no-letter",
                     "--region", "IE"]) == 0
    assert reports[0].ok and reports[0].pages <= 2, reports[0].problems
    text = "\n".join(p.extract_text() for p in PdfReader(next(app.glob("*_CV_*.pdf"))).pages)
    for line in ("Requires employment permit (Critical Skills occupation)", "Relocating to Ireland",
                 "References available on request"):
        assert line in text

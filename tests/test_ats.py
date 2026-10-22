from pathlib import Path

import pytest

from cvforge.build import compile_tex
from cvforge.checks import ats, layout
from cvforge.checks.ats import LAYOUT_SKIPPED, AtsReport, ats_check
from cvforge.profile.model import load_master
from cvforge.render.cv import render_cv
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
HEADINGS = ["Summary", "Experience", "Skills", "Education", "Certifications", "Languages"]
REQUIRED = ["Ana Exemplo", "Integração de pagamentos & reconciliação"]


@pytest.fixture(scope="module")
def cv_pdf(cfg):
    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    m = load_master(PERSONA / "master.yaml")
    t = load_tailored(PERSONA / "tailored.yaml")
    return compile_tex(render_cv(t, m), engine=cfg.lualatex,
                       build_dir=cfg.build_dir / "test_ats", jobname="cv_ats")


@pytest.fixture
def no_pdftotext(monkeypatch):
    layout.find_pdftotext.cache_clear()
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    yield
    monkeypatch.undo()
    layout.find_pdftotext.cache_clear()


@pytest.mark.latex
def test_persona_cv_is_ok(cv_pdf):
    report = ats_check(cv_pdf, max_pages=2, required=REQUIRED, headings=HEADINGS)
    assert isinstance(report, AtsReport)
    assert report.ok, report.problems
    assert report.pages <= 2
    assert report.extractor in ("pdftotext", "pypdf")


@pytest.mark.latex
def test_too_many_pages_reported(cv_pdf):
    report = ats_check(cv_pdf, max_pages=0)
    assert not report.ok
    assert any("page" in p for p in report.problems)


@pytest.mark.latex
def test_exact_pages_mismatch(cv_pdf):
    pages = ats_check(cv_pdf, max_pages=2).pages
    report = ats_check(cv_pdf, max_pages=pages + 1, exact_pages=True)
    assert not report.ok and any("exactly" in p for p in report.problems)


@pytest.mark.latex
def test_missing_required_and_heading_order(cv_pdf):
    report = ats_check(cv_pdf, max_pages=2, required=["projectzebra"],
                       headings=["Education", "Experience"])
    assert any("projectzebra" in p for p in report.problems)
    assert any("heading" in p for p in report.problems)


@pytest.mark.latex
def test_en_dash_date_range_reported(cfg):
    if not cfg.lualatex:
        pytest.skip("no lualatex engine")
    tex = ("\\documentclass{article}\n\\begin{document}\nEngineer 2020"
           + "\u2013" + "2021\n\\end{document}\n")
    pdf = compile_tex(tex, engine=cfg.lualatex, build_dir=cfg.build_dir / "test_ats",
                      jobname="endash")
    report = ats_check(pdf, max_pages=1)
    assert not report.ok
    assert any("date range" in p for p in report.problems)


@pytest.mark.latex
def test_layout_skipped_without_pdftotext_is_not_a_failure(cv_pdf, no_pdftotext):
    report = ats_check(cv_pdf, max_pages=2, required=REQUIRED, headings=HEADINGS)
    assert report.extractor == "pypdf"
    assert LAYOUT_SKIPPED in report.problems
    assert report.ok


def test_cid_and_replacement_char(monkeypatch):
    monkeypatch.setattr(ats, "extract_text_layer", lambda p: ("a (cid:12) b \ufffd", 1, "pypdf"))
    monkeypatch.setattr(ats, "_layout_problems", lambda p: [LAYOUT_SKIPPED])
    report = ats_check(Path("x.pdf"), max_pages=1)
    assert not report.ok
    assert any("(cid:" in p for p in report.problems)
    assert any("U+FFFD" in p for p in report.problems)


def test_skip_note_alone_keeps_ok(monkeypatch):
    monkeypatch.setattr(ats, "extract_text_layer", lambda p: ("Ana Exemplo", 1, "pypdf"))
    monkeypatch.setattr(ats, "_layout_problems", lambda p: [LAYOUT_SKIPPED])
    report = ats_check(Path("x.pdf"), max_pages=1, required=["Ana   Exemplo"])
    assert report.ok and report.problems == [LAYOUT_SKIPPED]


def test_layout_orphans_fail(monkeypatch):
    monkeypatch.setattr(ats, "extract_text_layer", lambda p: ("text", 1, "pdftotext"))
    monkeypatch.setattr(layout, "find_pdftotext", lambda: "/usr/bin/pdftotext")
    monkeypatch.setattr(layout, "parse_pdf", lambda p: [])
    monkeypatch.setattr(layout, "find_orphans", lambda pages: ["p1 ends on a heading"])
    report = ats_check(Path("x.pdf"), max_pages=1)
    assert not report.ok and any("p1 ends on a heading" in p for p in report.problems)


def test_unreadable_pdf_is_reported_not_raised(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    report = ats_check(bad, max_pages=1)
    assert not report.ok

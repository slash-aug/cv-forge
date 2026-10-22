import copy
from pathlib import Path

import pytest
from pypdf import PdfReader

from cvforge.build import LatexError, compile_tex
from cvforge.profile.model import load_master
from cvforge.render.cv import render_cv
from cvforge.render.letter import ASSETS_DIR, render_letter
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")


def _text(pdf):
    return "\n".join(p.extract_text() for p in PdfReader(pdf).pages)


def _need(cfg, name):
    if not getattr(cfg, name):
        pytest.skip(f"no {name}")
    return getattr(cfg, name)


def test_exe_engine_requires_mnt(tmp_path):
    with pytest.raises(LatexError, match="under /mnt/"):
        compile_tex("x", engine="/mnt/d/x/lualatex.exe", build_dir=tmp_path, jobname="t")


def test_exe_engine_symlink_escaping_mnt_rejected(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(LatexError, match="under /mnt/"):
        compile_tex("x", engine="/mnt/d/x/xelatex.exe", build_dir=link, jobname="t")


def test_no_engine_configured(tmp_path):
    with pytest.raises(LatexError, match="no LaTeX engine configured"):
        compile_tex("x", engine="", build_dir=tmp_path, jobname="t")


def test_missing_engine_binary_raises(tmp_path):
    with pytest.raises(LatexError, match="not found"):
        compile_tex("x", engine="/nonexistent/lualatex", build_dir=tmp_path, jobname="t")


def test_fresh_job_dir_is_wiped(tmp_path):
    job = tmp_path / "t"
    job.mkdir()
    (job / "stale.txt").write_text("old")
    with pytest.raises(LatexError):
        compile_tex("x", engine="/nonexistent/lualatex", build_dir=tmp_path, jobname="t")
    assert not (job / "stale.txt").exists()


@pytest.mark.latex
def test_persona_cv_compiles(cfg):
    pdf = compile_tex(render_cv(T, M), engine=_need(cfg, "lualatex"),
                      build_dir=cfg.build_dir / "test", jobname="cv")
    assert pdf.exists()
    assert len(PdfReader(pdf).pages) <= 2


@pytest.mark.latex
def test_bad_tex_raises_with_log(cfg):
    with pytest.raises(LatexError, match="Undefined control sequence"):
        compile_tex(r"\documentclass{article}\begin{document}\nope\end{document}",
                    engine=_need(cfg, "lualatex"), build_dir=cfg.build_dir / "test", jobname="bad")


@pytest.mark.latex
def test_persona_letter_compiles_to_one_page(cfg):
    pdf = compile_tex(render_letter(T, M), engine=_need(cfg, "xelatex"),
                      build_dir=cfg.build_dir / "test", jobname="letter", assets=ASSETS_DIR)
    assert pdf.exists()
    assert len(PdfReader(pdf).pages) == 1


@pytest.mark.latex
def test_special_chars_round_trip(cfg):
    text = "Integração & testes 100% #1 a_b"
    tailored = copy.deepcopy(T)
    tailored["experience"][1]["positions"][0]["bullets"][0]["text"] = text
    pdf = compile_tex(render_cv(tailored, M), engine=_need(cfg, "lualatex"),
                      build_dir=cfg.build_dir / "test", jobname="special")
    assert text in _text(pdf)

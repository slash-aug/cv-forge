import copy
from pathlib import Path

import pytest
from pypdf import PdfReader

from cvforge.build import JOBS_DIR, LatexError, compile_tex
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
    job = tmp_path / JOBS_DIR / "t"
    job.mkdir(parents=True)
    (job / "stale.txt").write_text("old")
    with pytest.raises(LatexError):
        compile_tex("x", engine="/nonexistent/lualatex", build_dir=tmp_path, jobname="t")
    assert not (job / "stale.txt").exists()


def test_user_folder_named_like_the_job_is_kept(tmp_path):
    mine = tmp_path / "cv"
    mine.mkdir()
    (mine / "keep.txt").write_text("mine")
    with pytest.raises(LatexError):
        compile_tex("x", engine="/nonexistent/lualatex", build_dir=tmp_path, jobname="cv")
    assert (mine / "keep.txt").read_text() == "mine"


@pytest.mark.latex
def test_persona_cv_compiles(cfg):
    pdf = compile_tex(render_cv(T, M), engine=_need(cfg, "lualatex"),
                      build_dir=cfg.build_dir / "test", jobname="cv", assets=ASSETS_DIR)
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
def test_pt_br_letter_keeps_accents_on_one_page(cfg):
    t = load_tailored(PERSONA / "tailored.pt-BR.yaml")
    pdf = compile_tex(render_letter(t, M), engine=_need(cfg, "xelatex"),
                      build_dir=cfg.build_dir / "test", jobname="letter_pt", assets=ASSETS_DIR)
    assert len(PdfReader(pdf).pages) == 1
    assert "integração e reconciliação" in " ".join(_text(pdf).split())


@pytest.mark.latex
def test_special_chars_round_trip(cfg):
    text = "Integração & testes 100% #1 a_b"
    tailored = copy.deepcopy(T)
    tailored["experience"][1]["positions"][0]["bullets"][0]["text"] = text
    pdf = compile_tex(render_cv(tailored, M), engine=_need(cfg, "lualatex"),
                      build_dir=cfg.build_dir / "test", jobname="special", assets=ASSETS_DIR)
    assert text in _text(pdf)


@pytest.mark.latex
def test_dashes_and_quotes_survive_without_ligatures(cfg):
    text = 'Shipped v2 -- then v3 --- "fast"'
    tailored = copy.deepcopy(T)
    tailored["experience"][1]["positions"][0]["bullets"][0]["text"] = text
    pdf = compile_tex(render_cv(tailored, M), engine=_need(cfg, "lualatex"),
                      build_dir=cfg.build_dir / "test", jobname="ligatures", assets=ASSETS_DIR)
    layer = _text(pdf)
    assert text in layer
    assert "\u2014" not in layer and "\u2013" not in layer


@pytest.mark.parametrize("jobname", ["", ".", "..", "../x", "a/b", "ABS", ".hidden", "a..b"])
def test_unsafe_jobname_rejected_before_touching_fs(tmp_path, jobname):
    build = tmp_path / "build"
    build.mkdir()
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("keep")
    inner = build / "inner.txt"
    inner.write_text("keep")
    if jobname == "ABS":
        jobname = str(tmp_path)
    with pytest.raises(LatexError, match="jobname"):
        compile_tex("x", engine="/bin/true", build_dir=build, jobname=jobname)
    assert sentinel.exists() and inner.exists() and tmp_path.exists()


def test_exe_check_is_case_insensitive(tmp_path):
    with pytest.raises(LatexError, match="under /mnt/"):
        compile_tex("x", engine="/mnt/d/x/LuaLaTeX.EXE", build_dir=tmp_path, jobname="t")


def test_timeout_raises_latex_error(tmp_path):
    stub = tmp_path / "slow.sh"
    stub.write_text("#!/bin/sh\nsleep 30\n")
    stub.chmod(0o755)
    with pytest.raises(LatexError, match="timed out"):
        compile_tex("x", engine=str(stub), build_dir=tmp_path / "b", jobname="t", timeout=1)

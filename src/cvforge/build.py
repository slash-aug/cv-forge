"""Compile LaTeX sources, natively or through a Windows engine from WSL."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

LOG_TAIL_LINES = 30


class LatexError(RuntimeError):
    """LaTeX compilation failed or could not be started."""


def _clean(text: str) -> str:
    return text.replace("\r", "")


def _log_tail(job_dir: Path, jobname: str, fallback: str = "") -> str:
    log = job_dir / f"{jobname}.log"
    text = _clean(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else _clean(fallback)
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])


def compile_tex(
    tex_source: str,
    *,
    engine: str,
    build_dir: Path,
    jobname: str,
    assets: Path | None = None,
    timeout: int = 300,
) -> Path:
    """Compile tex_source in a fresh build_dir/jobname and return the PDF path."""
    if not engine:
        raise LatexError("no LaTeX engine configured")
    build_dir = Path(build_dir)
    if engine.endswith(".exe"):
        try:
            build_dir.resolve().relative_to("/mnt")
        except ValueError:
            raise LatexError(
                f"Windows engine needs a build dir under /mnt/ (got {build_dir.resolve()})"
            ) from None

    job_dir = build_dir / jobname
    shutil.rmtree(job_dir, ignore_errors=True)
    job_dir.mkdir(parents=True)
    if assets is not None:
        shutil.copytree(assets, job_dir, dirs_exist_ok=True)
    (job_dir / f"{jobname}.tex").write_text(tex_source, encoding="utf-8")

    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", f"{jobname}.tex"]
    try:
        proc = subprocess.run(cmd, cwd=job_dir, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise LatexError(f"LaTeX engine not found: {engine}") from None
    except subprocess.TimeoutExpired:
        raise LatexError(
            f"LaTeX timed out after {timeout}s\n{_log_tail(job_dir, jobname)}"
        ) from None

    pdf = job_dir / f"{jobname}.pdf"
    if proc.returncode != 0 or not pdf.exists():
        out = proc.stdout.decode("utf-8", errors="replace")
        raise LatexError(
            f"LaTeX failed (exit {proc.returncode})\n{_log_tail(job_dir, jobname, out)}"
        )
    return pdf

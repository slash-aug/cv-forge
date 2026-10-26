"""Compile LaTeX sources, natively or through a Windows engine from WSL."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

LOG_TAIL_LINES = 30
# Jobs live in this tool-owned subfolder, so wiping a job never touches a user folder
# that happens to share its name (for example build_dir=/mnt/d with a "cv" folder).
JOBS_DIR = ".cvforge-jobs"
# Each build gets its own job folder, so builds can run at the same time. Folders older
# than this are swept on the next build; a build never runs this long (see timeout).
STALE_JOB_SECONDS = 24 * 60 * 60


class LatexError(RuntimeError):
    """LaTeX compilation failed or could not be started."""


def _clean(text: str) -> str:
    return text.replace("\r", "")


def _log_tail(job_dir: Path, jobname: str, fallback: str = "") -> str:
    log = job_dir / f"{jobname}.log"
    text = _clean(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else _clean(fallback)
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])


def _sweep_stale_jobs(jobs_dir: Path) -> None:
    cutoff = time.time() - STALE_JOB_SECONDS
    for job in jobs_dir.iterdir():
        try:
            if job.is_dir() and not job.is_symlink() and job.stat().st_mtime < cutoff:
                shutil.rmtree(job, ignore_errors=True)
        except FileNotFoundError:
            pass  # another build swept it first


def compile_tex(
    tex_source: str,
    *,
    engine: str,
    build_dir: Path,
    jobname: str,
    assets: Path | None = None,
    timeout: int = 300,
) -> Path:
    """Compile tex_source in a new folder under build_dir/.cvforge-jobs and return the PDF path.

    The folder is unique to this call, so builds with the same jobname can run in parallel.
    """
    if not engine:
        raise LatexError("no LaTeX engine configured")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", jobname) or ".." in jobname:
        raise LatexError(f"unsafe jobname: {jobname!r}")
    build_dir = Path(build_dir)
    if engine.lower().endswith(".exe"):
        try:
            build_dir.resolve().relative_to("/mnt")
        except ValueError:
            raise LatexError(
                f"Windows engine needs a build dir under /mnt/ (got {build_dir.resolve()})"
            ) from None

    jobs_dir = build_dir / JOBS_DIR
    jobs_dir.mkdir(parents=True, exist_ok=True)
    _sweep_stale_jobs(jobs_dir)
    job_dir = Path(tempfile.mkdtemp(prefix=f"{jobname}-", dir=jobs_dir))
    if job_dir.resolve().parent != jobs_dir.resolve():
        raise LatexError(f"jobname escapes build dir: {jobname!r}")
    if assets is not None:
        shutil.copytree(assets, job_dir, dirs_exist_ok=True)
    (job_dir / f"{jobname}.tex").write_text(tex_source, encoding="utf-8")

    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", f"{jobname}.tex"]
    try:
        proc = subprocess.Popen(
            cmd, cwd=job_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    except FileNotFoundError:
        raise LatexError(f"LaTeX engine not found: {engine}") from None
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the whole group; Windows grandchildren started via interop may survive.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise LatexError(
            f"LaTeX timed out after {timeout}s\n{_log_tail(job_dir, jobname)}"
        ) from None

    pdf = job_dir / f"{jobname}.pdf"
    if proc.returncode != 0 or not pdf.exists():
        out = stdout.decode("utf-8", errors="replace")
        raise LatexError(
            f"LaTeX failed (exit {proc.returncode})\n{_log_tail(job_dir, jobname, out)}"
        )
    return pdf

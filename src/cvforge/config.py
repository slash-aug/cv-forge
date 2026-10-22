"""Configuration: env vars, then cvforge.toml, then defaults."""
from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
MIKTEX_BIN = Path("/mnt/d/MiKTeX/miktex/bin/x64")
WIN_BUILD_DIR = Path("/mnt/d/cv-forge-build")


@dataclass(frozen=True)
class Config:
    data_dir: Path
    build_dir: Path
    lualatex: str
    xelatex: str
    daily_cap: int = 10
    clt_factor: float = 1.4


def _engine(name: str) -> str:
    exe = MIKTEX_BIN / f"{name}.exe"
    if exe.exists():
        return str(exe)
    return shutil.which(name) or ""


def _read_file(file: Path | None) -> dict:
    if file is None:
        file = REPO_ROOT / "cvforge.toml"
    if not file.exists():
        return {}
    with file.open("rb") as fh:
        return tomllib.load(fh).get("cvforge", {})


def load_config(env: Mapping[str, str] | None = None, file: Path | None = None) -> Config:
    env = os.environ if env is None else env
    cfg = _read_file(file)

    def pick(key: str) -> str | None:
        return env.get(f"CVFORGE_{key.upper()}") or cfg.get(key) or None

    raw_factor = pick("clt_factor")
    try:
        clt_factor = float(raw_factor) if raw_factor is not None else 1.4
    except (TypeError, ValueError):
        raise ValueError(f"clt_factor must be a number, got {raw_factor!r}") from None

    default_build = WIN_BUILD_DIR if Path("/mnt/d").exists() else REPO_ROOT / "build"
    return Config(
        data_dir=Path(pick("data_dir") or REPO_ROOT / "data"),
        build_dir=Path(pick("build_dir") or default_build),
        lualatex=pick("lualatex") or _engine("lualatex"),
        xelatex=pick("xelatex") or _engine("xelatex"),
        daily_cap=int(pick("daily_cap") or 10),
        clt_factor=clt_factor,
    )

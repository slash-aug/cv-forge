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


GUPY_KEYWORDS = ("react", "node", "full stack", "typescript")


class ConfigError(ValueError):
    """A configuration value or cvforge.toml that cannot be used."""


@dataclass(frozen=True)
class Config:
    data_dir: Path
    build_dir: Path
    lualatex: str
    xelatex: str
    daily_cap: int = 10
    clt_factor: float = 1.4
    serve_port: int = 47321
    gupy_keywords: tuple[str, ...] = GUPY_KEYWORDS


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
    try:
        with file.open("rb") as fh:
            return tomllib.load(fh).get("cvforge", {})
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file}: {exc}") from None


def load_config(env: Mapping[str, str] | None = None, file: Path | None = None) -> Config:
    env = os.environ if env is None else env
    cfg = _read_file(file)

    def pick(key: str) -> str | None:
        return env.get(f"CVFORGE_{key.upper()}") or cfg.get(key) or None

    raw_factor = pick("clt_factor")
    try:
        clt_factor = float(raw_factor) if raw_factor is not None else 1.4
    except (TypeError, ValueError):
        raise ConfigError(f"clt_factor must be a number, got {raw_factor!r}") from None
    raw_cap = pick("daily_cap")
    try:
        daily_cap = int(raw_cap) if raw_cap is not None else 10
    except (TypeError, ValueError):
        raise ConfigError(f"daily_cap must be a whole number, got {raw_cap!r}") from None
    raw_port = pick("serve_port")
    try:
        serve_port = int(raw_port) if raw_port is not None else 47321
    except (TypeError, ValueError):
        raise ConfigError(f"serve_port must be a whole number, got {raw_port!r}") from None
    if not 0 <= serve_port <= 65535:
        raise ConfigError(f"serve_port must be between 0 and 65535, got {serve_port}")

    raw_keywords = env.get("CVFORGE_GUPY_KEYWORDS")
    if raw_keywords:
        gupy_keywords = tuple(k.strip() for k in raw_keywords.split(",") if k.strip())
    else:
        file_keywords = cfg.get("gupy_keywords")
        if file_keywords is None:
            gupy_keywords = GUPY_KEYWORDS
        elif isinstance(file_keywords, list) and all(isinstance(k, str) for k in file_keywords):
            gupy_keywords = tuple(k.strip() for k in file_keywords if k.strip())
        else:
            raise ConfigError(f"gupy_keywords must be a list of strings, got {file_keywords!r}")

    default_build = WIN_BUILD_DIR if Path("/mnt/d").exists() else REPO_ROOT / "build"
    return Config(
        data_dir=Path(pick("data_dir") or REPO_ROOT / "data"),
        build_dir=Path(pick("build_dir") or default_build),
        lualatex=pick("lualatex") or _engine("lualatex"),
        xelatex=pick("xelatex") or _engine("xelatex"),
        daily_cap=daily_cap,
        clt_factor=clt_factor,
        serve_port=serve_port,
        gupy_keywords=gupy_keywords,
    )

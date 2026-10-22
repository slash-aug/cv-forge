"""Privacy and attribution guards, run by the git hooks."""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from cvforge.config import Config
from cvforge.profile.model import ProfileError, load_master
from cvforge.text import contains_term, fold

BLOCKED_PREFIXES = ("data/", ".claude/agents/", ".claude/local/", "docs/superpowers/", ".superpowers/")
BLOCKED_NAMES = ("*.env", "cvforge.toml")
CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
PHONE_BR = re.compile(r"\+55\s?\(?\d{2}\)?\s?9?\d{4}-?\d{4}")
EM_DASH = "\u2014"
EM_DASH_FORMS = (EM_DASH, "\\text" + "emdash", "&m" + "dash;", "&#82" + "12;", "&#x20" + "14;")
TRAILER = re.compile(r"(?im)^co-authored-by:.*(claude|anthropic)")
GENERATED = re.compile(r"(?i)\b(generated|created|written|made)\s+(with|by|using)\b.*\b(claude|anthropic)\b")
ANTHROPIC_NOREPLY = re.compile(r"(?i)noreply@anthropic\.com")
SCISSORS = "# " + "-" * 24 + " >8 " + "-" * 24
BINARY_PROBE = 8192


class GuardError(Exception):
    """The guard could not do its job; callers must fail closed."""


def check_paths(paths: Iterable[str]) -> list[str]:
    problems = []
    for path in paths:
        norm = path.replace("\\", "/").removeprefix("./")
        name = norm.rsplit("/", 1)[-1]
        if norm.startswith(BLOCKED_PREFIXES) or any(fnmatch.fnmatch(name, p) for p in BLOCKED_NAMES):
            problems.append(f"{path}: private path must not be committed")
    return problems


def check_content(text: str, *, denylist: Iterable[str]) -> list[str]:
    problems = []
    if any(contains_term(text, term) for term in denylist):
        problems.append("contains a denylisted term")
    if CPF.search(text):
        problems.append("contains a CPF number")
    if PHONE_BR.search(text):
        problems.append("contains a Brazilian phone number")
    if any(form in fold(text) for form in map(fold, EM_DASH_FORMS)):
        problems.append("contains an em dash")
    return problems


def check_commit_message(msg: str) -> list[str]:
    problems = []
    if TRAILER.search(msg) or GENERATED.search(msg) or ANTHROPIC_NOREPLY.search(msg):
        problems.append("AI attribution is not allowed in commit messages")
    if any(form in fold(msg) for form in map(fold, EM_DASH_FORMS)):
        problems.append("em dash is not allowed in commit messages")
    return problems


def load_denylist(cfg: Config) -> list[str]:
    path = cfg.data_dir / "profile" / "master.yaml"
    if not path.exists():
        return []
    try:
        master = load_master(path)
    except ProfileError as exc:
        raise GuardError(f"cannot load denylist from {path}: {exc}") from exc
    basics = master.get("basics", {})
    terms = list(master.get("x-confidential", [])) + [basics.get("email"), basics.get("phone")]
    return [t for t in terms if isinstance(t, str) and t.strip()]


def _top() -> str:
    return _git("rev-parse", "--show-toplevel").decode().strip()


def _git(*args: str, cwd: str | None = None) -> bytes:
    done = subprocess.run(["git", *args], capture_output=True, cwd=cwd, check=False)
    if done.returncode != 0:
        raise GuardError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def _denylist_warn(cfg: Config) -> list[str]:
    path = cfg.data_dir / "profile" / "master.yaml"
    if not path.exists():
        print(f"no master profile at {path}; denylist is empty", file=sys.stderr)
    return load_denylist(cfg)


def check_staged(cfg: Config) -> list[str]:
    denylist = _denylist_warn(cfg)
    top = _top()
    raw = _git("diff", "--cached", "--name-only", "--diff-filter=d", "-z", cwd=top)
    paths = [p for p in raw.decode("utf-8", errors="surrogateescape").split("\0") if p]
    problems = check_paths(paths)
    for path in paths:
        problems += [f"{path}: {p}" for p in check_content(path, denylist=denylist)]
        blob = _git("show", f":{path}", cwd=top)
        if b"\0" in blob[:BINARY_PROBE]:
            continue
        text = blob.decode("utf-8", errors="replace")
        problems += [f"{path}: {p}" for p in check_content(text, denylist=denylist)]
    return problems


def strip_message(text: str) -> str:
    """Drop the scissors section and git comment lines, as git does."""
    lines = []
    for line in text.splitlines():
        if line.startswith(SCISSORS):
            break
        if not line.startswith("#"):
            lines.append(line)
    return "\n".join(lines)


def check_message_file(path: Path, cfg: Config) -> list[str]:
    denylist = _denylist_warn(cfg)
    try:
        text = strip_message(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise GuardError(f"cannot read {path}: {exc}") from exc
    found = check_commit_message(text) + check_content(text, denylist=denylist)
    return [f"{path}: {p}" for p in found]

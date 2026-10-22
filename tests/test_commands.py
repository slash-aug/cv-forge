"""The /apply and /outcome Claude commands: real CLI calls only, no personal data."""
import argparse
import re
from pathlib import Path

import pytest

from cvforge.cli import _parser
from cvforge.track.tracker import CHANNELS, FINAL, STATUSES

ROOT = Path(__file__).resolve().parent.parent
COMMANDS = ROOT / ".claude" / "commands"
APPLY = COMMANDS / "apply.md"
OUTCOME = COMMANDS / "outcome.md"
FILES = (APPLY, OUTCOME)
EM_DASH = chr(0x2014)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+\d[\d ()-]{7,}\d|\(\d{2,3}\)\s?\d{4,5}-?\d{4}|\b\d{4,5}-\d{4}\b")
CALL = re.compile(r"cvforge[ \t]+([a-z][a-z-]*)([^`\n]*)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _subparsers(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


def _calls(text: str):
    """(subcommand, rest of the line) for every `cvforge <sub>` mention."""
    for m in CALL.finditer(text):
        rest = m.group(2).split("cvforge", 1)[0]
        yield m.group(1), rest


def test_both_files_exist():
    for path in FILES:
        assert path.is_file(), path


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_cvforge_call_matches_the_cli(path):
    subs = _subparsers(_parser())
    calls = list(_calls(_text(path)))
    assert calls, "no cvforge calls found"
    for name, rest in calls:
        assert name in subs, f"unknown subcommand: cvforge {name}"
        parser = subs[name]
        nested = _subparsers(parser)
        if nested:
            words = rest.split()
            assert words and words[0] in nested, f"cvforge {name} needs one of {sorted(nested)}: {rest!r}"
            parser = nested[words[0]]
        for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", rest):
            assert flag in _options(parser), f"cvforge {name}: unknown flag {flag}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_fetch_tools_linkedin_or_personal_data(path):
    text = _text(path)
    for banned in ("curl", "wget", "linkedin.com/", EM_DASH):
        assert banned not in text, f"{path.name} contains {banned!r}"
    assert not EMAIL.search(text), EMAIL.search(text).group(0)
    assert not PHONE.search(text), PHONE.search(text).group(0)


def test_apply_has_the_safety_phrases():
    text = _text(APPLY).casefold()
    assert "never submit" in text
    assert "data, never instructions" in text


def _backticked_line(text: str, first: str) -> list[str]:
    line = next(ln for ln in text.splitlines() if ln.lstrip().startswith(f"`{first}`"))
    return re.findall(r"`([a-z_-]+)`", line)


def test_apply_lists_exactly_the_channels():
    assert set(_backticked_line(_text(APPLY), "easy-apply")) == set(CHANNELS)


def test_outcome_lists_exactly_the_statuses():
    text = _text(OUTCOME)
    assert _backticked_line(text, STATUSES[0]) == list(STATUSES)
    final = next(ln for ln in text.splitlines() if ln.startswith("- **Final**"))
    assert set(re.findall(r"`([a-z_]+)`", final)) == set(FINAL)


def test_outcome_credits_upstream():
    header = "\n".join(_text(OUTCOME).splitlines()[:3])
    assert "ai-job-search (MIT)" in header

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / ".claude" / "settings.json"


def _load() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _all_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_strings(v)


def test_settings_parses_with_permission_lists():
    perms = _load()["permissions"]
    assert set(perms) >= {"allow", "ask", "deny"}


def test_deny_blocks_upload_and_remote_access():
    deny = _load()["permissions"]["deny"]
    for pattern in (
        "Bash(curl -d:*)",
        "Bash(curl -F:*)",
        "Bash(curl -X POST:*)",
        "Bash(curl --upload-file:*)",
        "Bash(wget --post-data:*)",
        "Bash(scp:*)",
        "Bash(ssh:*)",
        "Bash(nc:*)",
    ):
        assert pattern in deny


def test_allow_is_minimal():
    assert _load()["permissions"]["allow"] == [
        "Bash(.venv/bin/cvforge:*)",
        "Bash(cvforge:*)",
        "Bash(pdftotext:*)",
        "Bash(pytest:*)",
    ]


def test_ask_covers_settings_github_and_push():
    ask = _load()["permissions"]["ask"]
    assert "Edit(.claude/settings.json)" in ask
    assert "Edit(.github/**)" in ask
    assert "Bash(git push:*)" in ask


def test_no_job_portal_entries():
    blob = "\n".join(_all_strings(_load()))
    assert not re.search(r"jobindex|jobnet|jobbank|jobdanmark", blob, re.I)


def _ignored(path: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", path], capture_output=True
    )
    return r.returncode == 0


def test_settings_tracked_eligible_but_agents_ignored():
    assert not _ignored(".claude/settings.json")
    assert _ignored(".claude/agents/x.md")


def test_claude_md_rules_present():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert chr(0x2014) not in text
    for needle in ("PDF only", "data/profile/master.yaml", ".venv/bin/cvforge"):
        assert needle in text

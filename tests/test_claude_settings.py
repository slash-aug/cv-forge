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


UPSTREAM_DENY = [
    "Read(.env)", "Read(.env.*)", "Read(~/.ssh/**)", "Read(~/.aws/**)",
    "Read(~/.gnupg/**)", "Bash(curl -d:*)", "Bash(curl --data:*)",
    "Bash(curl -F:*)", "Bash(curl --form:*)", "Bash(curl -T:*)",
    "Bash(curl --upload-file:*)", "Bash(curl -X POST:*)", "Bash(curl -X PUT:*)",
    "Bash(curl -XPOST:*)", "Bash(curl --request POST:*)",
    "Bash(wget --post-data:*)", "Bash(wget --post-file:*)",
    "Bash(wget --method=POST:*)", "Bash(scp:*)", "Bash(sftp:*)", "Bash(ssh:*)",
    "Bash(nc:*)", "Bash(ncat:*)", "Bash(netcat:*)",
]
EXTRA_DENY = [
    "Bash(rsync:*)", "Bash(socat:*)", "Bash(telnet:*)", "Bash(ftp:*)",
    "Bash(openssl s_client:*)", "Bash(gh gist:*)", "Bash(gh release:*)",
    "Bash(gh repo create:*)", "Bash(curl --json:*)",
    "Bash(curl -X post:*)", "Bash(curl -sd:*)", "Bash(curl -s -d:*)",
    "Bash(curl -s -F:*)", "Bash(curl -sF:*)", "Bash(curl -s -X POST:*)",
    "Bash(curl -sX POST:*)",
]


def test_deny_is_superset_of_upstream_plus_extras():
    deny = set(_load()["permissions"]["deny"])
    assert set(UPSTREAM_DENY + EXTRA_DENY) <= deny


def test_ask_has_remote_and_guard_files():
    ask = _load()["permissions"]["ask"]
    assert "Bash(gh api:*)" not in _load()["permissions"]["deny"]
    for e in ("Bash(git remote:*)", "Edit(src/cvforge/guard.py)", "Edit(.githooks/**)"):
        assert e in ask


def test_allow_is_minimal():
    assert _load()["permissions"]["allow"] == [
        "Bash(.venv/bin/cvforge:*)",
        "Bash(cvforge:*)",
        "Bash(pdftotext:*)",
        "Bash(pytest:*)",
    ]


def test_ask_covers_settings_and_github():
    ask = _load()["permissions"]["ask"]
    assert "Edit(.claude/settings.json)" in ask
    assert "Edit(.github/**)" in ask


def test_no_job_portal_entries():
    blob = "\n".join(_all_strings(_load()))
    assert not re.search(r"jobindex|jobnet|jobbank|jobdanmark", blob, re.IGNORECASE)


def _ignored(path: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", path], capture_output=True, check=False
    )
    return r.returncode == 0


def test_settings_tracked_eligible_but_agents_ignored():
    assert not _ignored(".claude/settings.json")
    assert not _ignored(".claude/commands/apply.md")
    assert not _ignored(".claude/commands/outcome.md")
    assert _ignored(".claude/agents/x.md")


def test_claude_md_rules_present():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert chr(0x2014) not in text
    for needle in ("Never commit `data/`", "The human always clicks submit",
                   "No AI attribution", "PDF only", "data/profile/master.yaml", ".venv/bin/cvforge"):
        assert needle in text

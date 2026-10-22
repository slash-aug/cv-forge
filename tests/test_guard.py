import subprocess
from pathlib import Path

import pytest

from cvforge.cli import main
from cvforge.config import Config
from cvforge.guard import (GuardError, check_commit_message, check_content,
                           check_paths, load_denylist)

DASH = chr(0x2014)
CPF = "123.456" + ".789-09"
PHONE = "+" + "55 11 91234-5678"


def test_data_path_blocked():
    assert check_paths(["data/profile/master.yaml"])


def test_local_ai_tools_blocked():
    assert check_paths([".claude/agents/executor.md", ".claude/local/paradigms/x.md"])


def test_planning_scratch_blocked():
    assert check_paths([".superpowers/sdd/plan.md", "docs/superpowers/x.md"])


def test_env_and_toml_blocked():
    assert check_paths(["prod.env", "sub/cvforge.toml"])


def test_normal_paths_ok():
    assert check_paths(["src/cvforge/guard.py", "database/x.py", "README.md"]) == []


def test_cpf_blocked():
    assert check_content("cpf " + CPF, denylist=[])


def test_phone_blocked():
    assert check_content("call " + PHONE, denylist=[])


def test_em_dash_blocked():
    assert check_content("fast " + DASH + " reliable", denylist=[])


def test_denylist_case_insensitive():
    assert check_content("ProjectZebra api", denylist=["projectzebra"])


def test_blank_denylist_terms_ignored():
    assert check_content("plain text", denylist=["", "   "]) == []


def test_clean_content_ok():
    assert check_content("plain text 2026", denylist=["projectzebra"]) == []


def test_claude_trailer_blocked():
    assert check_commit_message("feat: x\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>")


def test_generated_with_blocked():
    assert check_commit_message("x\n\nGenerated with [Claude Code](https://x)")


def test_message_em_dash_blocked():
    assert check_commit_message("feat: a " + DASH + " b")


def test_clean_message_ok():
    assert check_commit_message("feat: add guard") == []


def _cfg(tmp_path):
    return Config(data_dir=tmp_path, build_dir=tmp_path, lualatex="", xelatex="")


def test_denylist_without_master_is_empty(tmp_path):
    assert load_denylist(_cfg(tmp_path)) == []


def test_denylist_from_master(tmp_path):
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "master.yaml").write_text(
        (Path(__file__).parents[1] / "examples/persona/master.yaml").read_text())
    terms = load_denylist(_cfg(tmp_path))
    assert "ana.exemplo@example.com" in [t.lower() for t in terms]


def test_denylist_fails_closed_on_broken_master(tmp_path):
    prof = tmp_path / "profile"
    prof.mkdir()
    (prof / "master.yaml").write_text("not: a valid master")
    with pytest.raises(GuardError):
        load_denylist(_cfg(tmp_path))


def _repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path / "nodata"))
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    return tmp_path


def _stage(*names):
    subprocess.run(["git", "add", *names], check=True)


def test_guard_staged_flags_index_content(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "a.txt").write_text("cpf " + CPF)
    _stage("a.txt")
    (tmp_path / "a.txt").write_text("clean now")  # working tree differs from index
    assert main(["guard", "staged"]) == 1
    assert "a.txt:" in capsys.readouterr().out


def test_guard_staged_clean_and_binary_skipped(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "ok.txt").write_text("fine")
    (tmp_path / "b.bin").write_bytes(b"\x00" + (CPF + DASH).encode())
    _stage("ok.txt", "b.bin")
    assert main(["guard", "staged"]) == 0


def test_guard_staged_blocks_path(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.txt").write_text("hi")
    _stage("data/x.txt")
    assert main(["guard", "staged"]) == 1
    assert "data/x.txt:" in capsys.readouterr().out


def test_guard_staged_ignores_deleted(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "a.txt").write_text("fine")
    _stage("a.txt")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
    subprocess.run(["git", "rm", "-q", "a.txt"], check=True)
    assert main(["guard", "staged"]) == 0


def test_guard_msg(tmp_path, capsys):
    good = tmp_path / "g"
    good.write_text("feat: ok\n")
    bad = tmp_path / "b"
    bad.write_text("x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    assert main(["guard", "msg", str(good)]) == 0
    assert main(["guard", "msg", str(bad)]) == 1

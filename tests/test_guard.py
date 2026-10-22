import subprocess
from pathlib import Path

import pytest

from cvforge.cli import main
from cvforge.config import Config
from cvforge.guard import (
    GuardError,
    check_commit_message,
    check_content,
    check_paths,
    load_denylist,
)

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


SCISSORS = "# " + "-" * 24 + " >8 " + "-" * 24


def _data_dir(tmp_path, monkeypatch):
    prof = tmp_path / "datadir" / "profile"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "master.yaml").write_text(
        (Path(__file__).parents[1] / "examples/persona/master.yaml").read_text())
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path / "datadir"))


def test_staged_real_denylist_uppercase_email(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _data_dir(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    subprocess.run(["git", "init", "-q"], check=True)
    (repo / "n.txt").write_text("mail ANA.EXEMPLO@EXAMPLE.COM")
    _stage("n.txt")
    assert main(["guard", "staged"]) == 1
    assert "n.txt:" in capsys.readouterr().out


def test_staged_file_name_checked(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _data_dir(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    subprocess.run(["git", "init", "-q"], check=True)
    (repo / "ProjectZebra-notes.md").write_text("fine")
    _stage("ProjectZebra-notes.md")
    assert main(["guard", "staged"]) == 1
    assert "ProjectZebra-notes.md:" in capsys.readouterr().out


def test_rename_into_data_blocked(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "a.txt").write_text("some stable content here")
    _stage("a.txt")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
    (tmp_path / "data").mkdir()
    subprocess.run(["git", "mv", "a.txt", "data/a.txt"], check=True)
    assert main(["guard", "staged"]) == 1
    assert "data/a.txt:" in capsys.readouterr().out


def test_path_with_spaces_and_non_ascii(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    name = "my fíle ç.txt"
    (tmp_path / name).write_text("cpf " + CPF)
    _stage(name)
    assert main(["guard", "staged"]) == 1
    assert name + ":" in capsys.readouterr().out


def test_staged_from_subdirectory(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("cpf " + CPF)
    _stage("sub/a.txt")
    monkeypatch.chdir(tmp_path / "sub")
    assert main(["guard", "staged"]) == 1


def test_missing_master_warns(tmp_path, monkeypatch, capsys):
    _repo(tmp_path, monkeypatch)
    (tmp_path / "ok.txt").write_text("fine")
    _stage("ok.txt")
    assert main(["guard", "staged"]) == 0
    assert "no master profile at" in capsys.readouterr().err
    f = tmp_path / "m"
    f.write_text("feat: ok\n")
    assert main(["guard", "msg", str(f)]) == 0
    assert "denylist is empty" in capsys.readouterr().err


@pytest.mark.parametrize("msg", [
    "x\n\nCO-AUTHORED-BY: CLAUDE <a@b.c>",
    "x\n\nco-authored-by: Someone <noreply@anthropic.com>",
    "x\n\nCreated by Claude Code",
    "x\n\nwritten using Anthropic tools",
    "contact noreply@anthropic.com",
])
def test_attribution_variants_blocked(msg):
    assert check_commit_message(msg)


@pytest.mark.parametrize("text", ["a \\text" + "emdash b", "a &m" + "dash; b", "a &#82" + "12; b", "a &#x20" + "14; b"])
def test_em_dash_variants_blocked(text):
    assert check_content(text, denylist=[])


def test_denylist_unicode_normalized():
    assert check_content("José rocks", denylist=["José"])


def _msg_file(tmp_path, monkeypatch, body):
    _data_dir(tmp_path, monkeypatch)
    f = tmp_path / "msg"
    f.write_text(body)
    return str(f)


def test_msg_content_rules(tmp_path, monkeypatch):
    for body in ["feat: projectzebra", "feat: cpf " + CPF, "feat: call " + PHONE]:
        assert main(["guard", "msg", _msg_file(tmp_path, monkeypatch, body)]) == 1


def test_msg_comments_and_scissors_stripped(tmp_path, monkeypatch):
    body = ("feat: ok\n# projectzebra in a comment\n" + SCISSORS +
            "\ndiff --git a/x b/x\n+projectzebra " + DASH + " " + CPF + "\n")
    assert main(["guard", "msg", _msg_file(tmp_path, monkeypatch, body)]) == 0

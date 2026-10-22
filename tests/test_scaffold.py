import subprocess

import cvforge


def test_version():
    assert cvforge.__version__ == "0.1.0"


def _ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path], check=False).returncode == 0


def test_data_dir_is_ignored():
    assert _ignored("data/profile/master.yaml")


def test_local_ai_tools_are_ignored():
    for p in [".claude/agents/executor.md", ".claude/local/paradigms/1_coding_paradigm.md", "docs/superpowers/plans/x.md"]:
        assert _ignored(p), p


def test_env_files_are_ignored():
    for p in [".env", ".env.local"]:
        assert _ignored(p), p

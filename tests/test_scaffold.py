import subprocess, cvforge
def test_version():
    assert cvforge.__version__ == "0.1.0"
def test_data_dir_is_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", "data/profile/master.yaml"])
    assert r.returncode == 0
def test_local_ai_tools_are_ignored():
    for p in [".claude/agents/executor.md", ".claude/local/paradigms/1_coding_paradigm.md", "docs/superpowers/plans/x.md"]:
        assert subprocess.run(["git", "check-ignore", "-q", p]).returncode == 0, p

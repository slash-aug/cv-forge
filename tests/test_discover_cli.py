import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.apply.http import FetchError
from cvforge.apply.seed import SEED_NOTE
from cvforge.config import Config
from cvforge.discover import run as discover_run
from cvforge.discover.sources import board_url

NOW = datetime(2026, 10, 28, 9, 0)
FEEDS = Path(__file__).parent / "fixtures" / "feeds"
ACME_URL = board_url("greenhouse", "acme")
GLOBEX_URL = board_url("ashby", "globex")
REGISTRY = [{"name": "Acme", "ats": "greenhouse", "slug": "acme", "sponsor": [], "notes": ""},
            {"name": "Globex", "ats": "ashby", "slug": "globex", "sponsor": [], "notes": SEED_NOTE}]


class Server:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.pages = {ACME_URL: (FEEDS / "greenhouse_board.json").read_text(encoding="utf-8"),
                      GLOBEX_URL: (FEEDS / "ashby_board.json").read_text(encoding="utf-8")}

    def __call__(self, url, **_):
        self.calls.append(url)
        if self.fail or url not in self.pages:
            raise FetchError(f"HTTP 503 for {url}")
        return self.pages[url]


@pytest.fixture
def env(tmp_path, monkeypatch, discover_master):
    (tmp_path / "companies.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "master.yaml").write_text("{}", encoding="utf-8")
    cfg = Config(data_dir=tmp_path, build_dir=tmp_path / "b", lualatex="", xelatex="")
    server = Server()
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "load_master", lambda path: discover_master)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli.apply_http, "get", server)
    monkeypatch.setattr(discover_run.time, "sleep", lambda s: None)
    return tmp_path


def test_jobs_fetch_cli(env, capsys):
    assert cli.main(["jobs", "fetch"]) == 0
    out = capsys.readouterr().out
    assert "fetched 5 roles from 2 of 2 sources" in out
    assert "dropped: out-of-market 2, " in out
    assert "shown: 3 Irish, 0 Brazilian (3 new)" in out
    assert str(env / "jobs" / "latest.html") in out
    assert (env / "jobs" / "latest.html").exists()


def test_jobs_fetch_dry_run(env, capsys):
    assert cli.main(["jobs", "fetch", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "(dry run, nothing written)" in out
    assert not (env / "jobs" / "latest.html").exists()


def test_jobs_fetch_all_failed_exits_1(env, capsys):
    env_server = cli.apply_http.get
    env_server.fail = True
    assert cli.main(["jobs", "fetch"]) == 1
    captured = capsys.readouterr()
    assert "fetched 0 roles from 0 of 2 sources" in captured.out
    assert "Acme (greenhouse)" in captured.err


def test_jobs_fetch_bad_args(env):
    with pytest.raises(SystemExit):
        cli.main(["jobs", "fetch", "--market", "XX"])
    with pytest.raises(SystemExit):
        cli.main(["jobs", "fetch", "--source", "nope"])


def test_jobs_refreshes_when_stale(env, monkeypatch, capsys):
    cli.main(["jobs", "fetch"])
    calls = []
    real = discover_run.run_fetch
    monkeypatch.setattr(cli, "run_fetch", lambda *a, **k: calls.append(1) or real(*a, **k))
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["at"] = (NOW - timedelta(hours=1)).isoformat()
    path.write_text(json.dumps(last), encoding="utf-8")
    assert cli.main(["jobs"]) == 0
    assert calls == []
    last["at"] = (NOW - timedelta(hours=24)).isoformat()
    path.write_text(json.dumps(last), encoding="utf-8")
    assert cli.main(["jobs"]) == 0
    assert calls == [1]


def test_jobs_fetches_when_never_run_and_lists(env, capsys):
    assert cli.main(["jobs"]) == 0
    out = capsys.readouterr().out
    assert "NEW Full Stack Engineer | Acme | " in out
    assert "  cvforge intake https://" in out
    assert f"page: {env / 'jobs' / 'latest.html'}" in out


def test_jobs_records_view(env, capsys):
    assert cli.main(["jobs"]) == 0
    assert "NEW " in capsys.readouterr().out
    assert (env / "jobs" / "last_viewed.json").exists()
    assert cli.main(["jobs"]) == 0
    assert "NEW " not in capsys.readouterr().out


def test_jobs_applied_last_and_unsafe_url(env, capsys):
    cli.main(["jobs", "fetch"])
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["rows"][0]["applied"] = {"slug": "x", "status": "applied"}
    last["rows"][1]["url"] = "https://x.example/a\x1b[31mb"
    path.write_text(json.dumps(last), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["jobs"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "(open the link by hand: 'https://x.example/a\\x1b[31mb')" in out
    assert out.index("Already applied") > out.index("NEW ")
    assert last["rows"][0]["title"] in out.split("Already applied")[1]


def test_jobs_all_failed_keeps_old_list(env, capsys):
    cli.main(["jobs", "fetch"])
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["at"] = (NOW - timedelta(hours=30)).isoformat()
    path.write_text(json.dumps(last), encoding="utf-8")
    cli.apply_http.get.fail = True
    capsys.readouterr()
    assert cli.main(["jobs"]) == 0
    captured = capsys.readouterr()
    assert "Full Stack Engineer" in captured.out
    assert "Acme (greenhouse)" in captured.err


def test_jobs_all_failed_no_list_exits_1(env, capsys):
    cli.apply_http.get.fail = True
    assert cli.main(["jobs"]) == 1


def test_missing_master_is_clear(env, monkeypatch, capsys):
    from cvforge.profile.model import ProfileError

    def boom(path):
        raise ProfileError(f"{path}: cannot read master profile")

    monkeypatch.setattr(cli, "load_master", boom)
    assert cli.main(["jobs", "fetch"]) == 1
    assert "master" in capsys.readouterr().err


def test_due_includes_jobs_line(env, capsys):
    assert cli.main(["due"]) == 0
    out = capsys.readouterr().out
    assert "Jobs" in out
    assert "jobs: never fetched; run cvforge jobs fetch" in out


def test_jobs_list_strips_control_characters(env, capsys):
    cli.main(["jobs", "fetch"])
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["rows"][0]["title"] = "Dev\x1b[2J"
    last["rows"][0]["locations"] = ["Dub\x1b]0;x\x07lin"]
    path.write_text(json.dumps(last), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["jobs"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "Dev [2J" in out


def test_due_survives_corrupt_last_run(env, capsys):
    cli.main(["jobs", "fetch"])
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["at"] = "garbage"
    last["rows"][0]["first_seen"] = "garbage"
    path.write_text(json.dumps(last), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["due"]) == 0
    assert "last run unknown; run cvforge jobs fetch" in capsys.readouterr().out


def test_real_load_master_missing_file(env, monkeypatch, capsys):
    from cvforge.profile.model import load_master
    monkeypatch.setattr(cli, "load_master", load_master)
    (env / "profile" / "master.yaml").unlink()
    assert cli.main(["jobs", "fetch"]) == 1
    assert "master" in capsys.readouterr().err


def test_intake_command_refuses_control_and_format_urls(env, capsys):
    from cvforge.discover.rows import intake_command
    bad = ["https://x.example/a\x9b2J", "https://x.example/a\u202eb", "https://x.example/a\x1bb"]
    assert all(intake_command(u) is None for u in bad)
    cli.main(["jobs", "fetch"])
    path = env / "jobs" / "last_run.json"
    last = json.loads(path.read_text(encoding="utf-8"))
    last["rows"][0]["url"] = bad[0]
    last["rows"][1]["url"] = bad[1]
    path.write_text(json.dumps(last), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["jobs"]) == 0
    out = capsys.readouterr().out
    assert "\x9b" not in out and "\u202e" not in out
    assert out.count("(open the link by hand:") == 2

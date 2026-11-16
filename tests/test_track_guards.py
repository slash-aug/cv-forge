from datetime import date

import pytest

from cvforge.cli import main
from cvforge.track import tracker
from cvforge.track.due import due_report
from cvforge.track.stages import StagesError, load_stages


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("cvforge.cli._today", lambda: date(2026, 5, 1))
    return tmp_path


def test_add_existing_slug_exits_3_without_writing(data, capsys):
    assert main(["track", "add", "a", "--company", "Acme", "--role", "Dev", "--url", "http://x/1"]) == 0
    main(["track", "status", "a", "applied", "--note", "sent"])
    before = (data / "tracker.csv").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["track", "add", "a", "--company", "Acme", "--role", "Dev"]) == 3
    assert "already tracked: a (applied)" in capsys.readouterr().out
    assert main(["track", "add", "b", "--company", "acme", "--role", "dev"]) == 3
    assert main(["track", "add", "c", "--company", "Z", "--role", "Q", "--url", "http://x/1"]) == 3
    assert (data / "tracker.csv").read_text(encoding="utf-8") == before


def test_due_falls_back_to_date_for_legacy_rows(tmp_path):
    legacy = {c: "" for c in tracker.COLUMNS}
    legacy.update(slug="old", company="O", role="R", status="applied", date="2026-06-01")
    neither = dict(legacy, slug="none", date="")
    rep = due_report([legacy, neither], tmp_path, date(2026, 6, 30))
    assert [r["slug"] for r in rep.followups] == ["old"]
    assert rep.stale == []


def test_stage_and_done_unknown_slug_write_nothing(data, capsys):
    main(["track", "add", "a", "--company", "A", "--role", "R"])
    assert main(["track", "stage", "typo", "Call", "--kind", "interview"]) == 1
    assert main(["track", "done", "typo", "Call"]) == 1
    assert capsys.readouterr().err
    assert not (data / "applications" / "typo").exists()


def test_load_stages_null_and_invalid(tmp_path):
    (tmp_path / "stages.yaml").write_text("stages:\n", encoding="utf-8")
    assert load_stages(tmp_path) == []
    (tmp_path / "stages.yaml").write_text("stages:\n  - name: x\n    due: nope\n", encoding="utf-8")
    with pytest.raises(StagesError, match="stages.yaml"):
        load_stages(tmp_path)
    (tmp_path / "stages.yaml").write_text("stages: 5\n", encoding="utf-8")
    with pytest.raises(StagesError):
        load_stages(tmp_path)


def test_due_reports_bad_stage_file_and_continues(data, capsys):
    main(["track", "add", "bad", "--company", "B", "--role", "R"])
    main(["track", "add", "good", "--company", "G", "--role", "R"])
    main(["track", "stage", "good", "Test", "--kind", "test", "--due", "2026-05-02"])
    (data / "applications" / "bad").mkdir(parents=True)
    (data / "applications" / "bad" / "stages.yaml").write_text("stages: [{name: x, due: nope}]\n")
    capsys.readouterr()
    assert main(["due"]) == 1
    out = capsys.readouterr()
    assert "good: Test" in out.out
    assert "bad" in out.err and "stages.yaml" in out.err


def test_track_show_prints_row_and_stages(data, capsys):
    main(["track", "add", "acme-dev", "--company", "Acme", "--role", "Dev", "--url", "http://x/1",
          "--channel", "external"])
    main(["track", "status", "acme-dev", "applied", "--note", "sent"])
    main(["track", "stage", "acme-dev", "Online test", "--kind", "test", "--due", "2026-05-08"])
    main(["track", "stage", "acme-dev", "Screen", "--kind", "interview"])
    main(["track", "done", "acme-dev", "Screen"])
    before = (data / "tracker.csv").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["track", "show", "acme-dev"]) == 0
    out = capsys.readouterr().out
    for line in ("slug: acme-dev", "status: applied", "channel: external", "date: 2026-05-01",
                 "company: Acme", "role: Dev", "url: http://x/1", "notes: sent", "skip_reason: -",
                 "days_quiet: ", "stages:", "  Online test (test) due 2026-05-08, open",
                 "  Screen (interview) due -, done"):
        assert line in out, line
    assert "last_update: " in out
    assert (data / "tracker.csv").read_text(encoding="utf-8") == before


def test_track_show_unknown_slug(data, capsys):
    assert main(["track", "show", "nope"]) == 1
    assert "unknown slug 'nope'" in capsys.readouterr().err


def test_track_show_without_stages(data, capsys):
    main(["track", "add", "a", "--company", "A", "--role", "R"])
    capsys.readouterr()
    assert main(["track", "show", "a"]) == 0
    out = capsys.readouterr().out
    assert "status: drafted" in out
    assert "stages: -" in out


@pytest.mark.parametrize("args", [["stage", "a", "call", "--kind", "interview"],
                                  ["done", "a", "call"]])
def test_stage_and_done_report_bad_stages_file(data, capsys, args):
    main(["track", "add", "a", "--company", "A", "--role", "R"])
    app = data / "applications" / "a"
    app.mkdir(parents=True)
    (app / "stages.yaml").write_text("stages: {", encoding="utf-8")
    capsys.readouterr()
    assert main(["track", *args]) == 1
    err = capsys.readouterr().err
    assert "bad stages file" in err and "stages.yaml" in err
    assert (app / "stages.yaml").read_text(encoding="utf-8") == "stages: {"


def _pasted(data, slug="acme-dev"):
    from cvforge.apply.intake import posting_from_text
    posting_from_text("We need a developer to join the team.", company="Acme", role="Dev",
                      url="", today=date(2026, 5, 1)).save(data / "applications" / slug)
    main(["track", "add", slug, "--company", "Acme", "--role", "Dev"])


def test_track_url_sets_the_link_in_tracker_and_posting(data, capsys):
    from cvforge.apply.posting import Posting
    _pasted(data)
    capsys.readouterr()
    assert main(["track", "url", "acme-dev", "https://jobs.example/acme/dev?utm_source=li"]) == 0
    assert capsys.readouterr().out.strip() == "acme-dev: https://jobs.example/acme/dev"
    assert tracker.load(data / "tracker.csv")[0]["url"] == "https://jobs.example/acme/dev"
    app = data / "applications" / "acme-dev"
    assert Posting.load(app).url == "https://jobs.example/acme/dev"
    assert "- Link: https://jobs.example/acme/dev" in (app / "posting.md").read_text()


def test_track_url_refuses_bad_links_and_unknown_slugs(data, capsys):
    _pasted(data)
    main(["track", "add", "other", "--company", "Z", "--role", "Q", "--url", "https://jobs.example/z"])
    before = (data / "tracker.csv").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["track", "url", "acme-dev", "https://www.linkedin.com/jobs/view/1"]) == 1
    assert "LinkedIn" in capsys.readouterr().err
    assert main(["track", "url", "nope", "https://jobs.example/x"]) == 1
    assert "unknown slug" in capsys.readouterr().err
    assert main(["track", "url", "acme-dev", "https://jobs.example/z"]) == 3
    assert "already tracked: other" in capsys.readouterr().out
    assert (data / "tracker.csv").read_text(encoding="utf-8") == before


def test_track_url_without_posting_updates_the_tracker_only(data):
    main(["track", "add", "manual", "--company", "Acme", "--role", "Dev"])
    assert main(["track", "url", "manual", "https://jobs.example/acme/dev"]) == 0
    assert tracker.load(data / "tracker.csv")[0]["url"] == "https://jobs.example/acme/dev"
    assert not (data / "applications" / "manual").exists()

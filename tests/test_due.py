from datetime import date

from cvforge.track.due import due_report
from cvforge.track.stages import add_stage, complete_stage

TODAY = date(2026, 6, 30)


def row(slug, status, last_update):
    return {"slug": slug, "status": status, "last_update": last_update, "company": slug}


def test_due_lists_overdue_and_window_stages(tmp_path):
    app = tmp_path / "a"
    add_stage(app, "overdue", "test", date(2026, 6, 20))
    add_stage(app, "soon", "interview", date(2026, 7, 5))
    add_stage(app, "later", "case", date(2026, 8, 1))
    add_stage(app, "nodate", "other", None)
    add_stage(app, "finished", "form", date(2026, 6, 1))
    complete_stage(app, "finished")
    rep = due_report([row("a", "interview", "2026-06-29")], tmp_path, TODAY)
    assert [(s, st.name) for s, st in rep.stages] == [("a", "overdue"), ("a", "soon")]


def test_followup_after_10_days_not_drafted(tmp_path):
    rows = [
        row("old-applied", "applied", "2026-06-15"),
        row("assess", "assessment", "2026-06-20"),
        row("fresh", "applied", "2026-06-25"),
        row("draft", "drafted", "2026-06-15"),
        row("interview", "interview", "2026-06-15"),
    ]
    rep = due_report(rows, tmp_path, TODAY)
    assert {r["slug"] for r in rep.followups} == {"old-applied", "assess"}


def test_stale_after_60_days(tmp_path):
    rows = [
        row("ancient", "applied", "2026-04-01"),
        row("ancient-int", "interview", "2026-04-01"),
        row("ancient-draft", "drafted", "2026-04-01"),
        row("ancient-final", "rejected", "2026-04-01"),
        row("edge", "applied", "2026-05-01"),
    ]
    rep = due_report(rows, tmp_path, TODAY)
    assert {r["slug"] for r in rep.stale} == {"ancient", "ancient-int", "edge"}
    assert not rep.followups

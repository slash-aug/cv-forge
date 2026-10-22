import csv
from datetime import date

import pytest

from cvforge.cli import main
from cvforge.track import tracker


def test_columns_order():
    assert tracker.COLUMNS == (
        "date", "company", "sector", "role", "role_type", "channel", "status", "contact_person",
        "fit_rating", "notes", "cv_file", "cover_letter_file", "source", "deadline",
        "slug", "url", "market", "posted_salary", "suggested_salary", "offered_salary",
        "skip_reason", "last_update",
    )
    assert "skipped" in tracker.STATUSES and "skipped" in tracker.FINAL
    assert "drafted" not in tracker.FINAL


def test_legacy_status_read(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text(
        "date,company,status\n2026-01-01,A,no response\n2026-01-02,B,offer declined\n",
        encoding="utf-8",
    )
    rows = tracker.load(path)
    assert [r["status"] for r in rows] == ["no_response", "offer_declined"]
    tracker.save(path, rows)
    assert "no response" not in path.read_text(encoding="utf-8")
    assert all(r["status"] in tracker.FINAL for r in rows)


@pytest.mark.parametrize("bad", ["=SUM(A1)", "+1", "-1", "@x", "\tx", "\rx"])
def test_csv_injection_prefixed(tmp_path, bad):
    path = tmp_path / "t.csv"
    tracker.save(path, [{"slug": "a", "company": "A", "notes": bad}])
    with path.open(newline="", encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))
    assert raw[0]["notes"] == "'" + bad
    assert raw[0]["company"] == "A"
    assert list(raw[0]) == list(tracker.COLUMNS)


def test_upsert_by_slug_sets_last_update(tmp_path, monkeypatch):
    path = tmp_path / "t.csv"
    monkeypatch.setattr(tracker, "_today", lambda: date(2026, 3, 1))
    tracker.upsert(path, {"slug": "acme-dev", "company": "Acme", "role": "Dev"})
    monkeypatch.setattr(tracker, "_today", lambda: date(2026, 3, 5))
    row = tracker.upsert(path, {"slug": "acme-dev", "notes": "hi"})
    rows = tracker.load(path)
    assert len(rows) == 1
    assert row["last_update"] == "2026-03-05"
    assert rows[0]["company"] == "Acme" and rows[0]["notes"] == "hi"


def test_find_by_url_or_folded_company_role():
    rows = [
        {"slug": "a", "company": "Café Ltda", "role": "Dev Júnior", "url": "http://x/1"},
        {"slug": "b", "company": "Other", "role": "Dev", "url": ""},
    ]
    assert tracker.find(rows, url="http://x/1")["slug"] == "a"
    assert tracker.find(rows, company="CAFE ltda", role="dev junior")["slug"] == "a"
    assert tracker.find(rows, company="Other", role="Ops") is None
    assert tracker.find(rows) is None


def test_set_status_and_applied_on(tmp_path):
    path = tmp_path / "t.csv"
    tracker.upsert(path, {"slug": "a", "company": "A", "notes": "first"})
    row = tracker.set_status(path, "a", "applied", date(2026, 4, 1), note="sent")
    assert row["status"] == "applied" and row["date"] == "2026-04-01"
    assert row["notes"] == "first; sent"
    assert tracker.applied_on(tracker.load(path), date(2026, 4, 1)) == 1
    assert tracker.applied_on(tracker.load(path), date(2026, 4, 2)) == 0
    with pytest.raises(ValueError):
        tracker.set_status(path, "a", "bogus", date(2026, 4, 1))
    with pytest.raises(KeyError):
        tracker.set_status(path, "zzz", "applied", date(2026, 4, 1))
    skipped = tracker.set_status(path, "a", "skipped", date(2026, 4, 2), skip_reason="low fit")
    assert skipped["skip_reason"] == "low fit"


def test_daily_cap_warns_not_blocks(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("cvforge.cli._today", lambda: date(2026, 5, 1))
    for i in range(11):
        assert main(["track", "add", f"s{i}", "--company", f"C{i}", "--role", "R"]) == 0
    for i in range(10):
        assert main(["track", "status", f"s{i}", "applied"]) == 0
    capsys.readouterr()
    assert main(["track", "status", "s10", "applied"]) == 0
    out = capsys.readouterr()
    assert "daily cap" in (out.out + out.err).lower()
    rows = tracker.load(tmp_path / "tracker.csv")
    assert tracker.applied_on(rows, date(2026, 5, 1)) == 11

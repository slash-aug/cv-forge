from datetime import datetime, timedelta

from cvforge.discover.rows import applied_match, build_rows
from cvforge.discover.screen import Outcome
from cvforge.discover.sources import Role

NOW = datetime(2026, 10, 28, 23, 5)
TEXT = "We build payment tools for small shops and need a frontend engineer who loves clean interfaces and testing"
OTHER = "Completely unrelated copy about warehouse robots and logistics planning across several continents each year"


def role(job_id="1", company="Acme Ltd", title="Frontend Engineer", location="Dublin, Ireland",
         description=TEXT, url=None):
    return Role(source="greenhouse", board="acme", job_id=job_id, company=company, title=title,
                location=location, workplace=None, url=url or f"https://x.test/{job_id}",
                description=description, salary={"min": 50000})


def outcome(market="IE", tags=None):
    return Outcome(market, None, "match", ["react"], "CSEP", None, list(tags or []))


def seen_for(*roles, first="2026-10-27T09:00:00", **extra):
    return {r.key: {"first_seen": first, "times_reposted": 0, **extra} for r in roles}


def build(roles, seen=None, registry=None, ghosts=None, tracker=None, last_viewed=None, outcomes=None):
    kept = [(r, (outcomes or {}).get(r.job_id, outcome())) for r in roles]
    return build_rows(kept, seen if seen is not None else seen_for(*roles), registry=registry or [],
                      ghosts=ghosts or {}, tracker_rows=tracker or [], last_viewed=last_viewed, now=NOW)


def test_clones_group_into_one_row():
    roles = [role("1"), role("2"), role("3")]
    rows, flagged = build(roles)
    assert len(rows) == 1
    assert "cloned ×3" in rows[0].tags
    assert flagged == {"Acme Ltd": "cloned"}
    assert rows[0].urls == [r.url for r in roles]


def test_different_descriptions_not_clones():
    rows, flagged = build([role("1"), role("2", description=OTHER)])
    assert len(rows) == 2
    assert not any(t.startswith("cloned") for r in rows for t in r.tags)
    assert flagged == {}


def test_multi_location_is_one_row_not_cloned():
    dublin = role("1")
    cork = role("2", location="Cork, Ireland", description=OTHER)
    remote = role("3", location="Remote - Ireland", description=TEXT + " extra")
    rows, flagged = build([dublin, cork, remote])
    assert len(rows) == 1 and rows[0].locations == ["Dublin, Ireland", "Cork, Ireland", "Remote - Ireland"]
    assert not any(t.startswith("cloned") for t in rows[0].tags) and flagged == {}


def test_applied_match_ignores_tracking_and_slash():
    row = {"url": "https://Boards.greenhouse.io/acme/jobs/101/?gh_src=abc", "company": "Acme", "role": "x",
           "date": "2026-10-01", "status": "applied"}
    got = applied_match(role(url="https://boards.greenhouse.io/acme/jobs/101"), [row])
    assert got["date"] == "2026-10-01"


def test_applied_by_company_and_title():
    row = {"url": "https://elsewhere.test/1", "company": "ACME Ltd", "role": "Frontend Engineer (m/f/d)",
           "date": "2026-10-01", "status": "applied"}
    assert applied_match(role(), [row]) == {"date": "2026-10-01", "status": "applied"}
    assert applied_match(role(title="Backend Engineer"), [row]) is None


def test_applied_row_not_new_and_tagged():
    row = {"url": "https://x.test/1", "company": "Acme", "role": "x", "date": "2026-10-01", "status": "applied"}
    rows, _ = build([role()], tracker=[row])
    assert "applied on 2026-10-01" in rows[0].tags and rows[0].new is False
    assert rows[0].applied == {"date": "2026-10-01", "status": "applied"}


def test_drafted_and_skipped_tags():
    drafted = {"url": "https://x.test/1", "company": "Acme", "role": "x", "date": "2026-10-01", "status": "drafted"}
    rows, _ = build([role()], tracker=[drafted])
    assert "in tracker (drafted)" in rows[0].tags and rows[0].new is False



def test_new_relative_to_last_viewed():
    r = role()
    seen = seen_for(r, first="2026-10-27T09:00:00")
    assert build([r], seen, last_viewed=datetime(2026, 10, 28))[0][0].new is False
    assert build([r], seen, last_viewed=datetime(2026, 10, 20))[0][0].new is True
    assert build([r], seen, last_viewed=None)[0][0].new is True


def test_stale_ghost_sponsor_tags():
    r = role()
    seen = seen_for(r, first=(NOW - timedelta(days=20)).isoformat(timespec="seconds"))
    ghosts = {"acme": {"name": "Acme", "last_flagged": "2026-10-01", "reason": "stale"}}
    registry = [{"name": "Acme", "sponsor": {"source": "dete"}}]
    rows, flagged = build([r], seen, registry=registry, ghosts=ghosts)
    assert rows[0].tags == ["stale", "ghost history", "sponsor"]
    assert flagged == {"Acme Ltd": "stale"}


def test_tag_order_and_outcome_tags_first():
    roles = [role("1"), role("2")]
    rows, _ = build(roles, outcomes={"1": outcome(tags=["salary unknown"])})
    assert rows[0].tags == ["salary unknown", "cloned ×2"]


def test_missing_seen_record_is_not_stale_and_new():
    r = role()
    rows, flagged = build([r], seen={})
    assert rows[0].new is True and "stale" not in rows[0].tags and flagged == {}
    assert rows[0].first_seen == "2026-10-28T23:05:00"


def test_sorting_market_new_then_newest():
    a = role("1", title="Alpha Engineer")
    b = role("2", title="Beta Engineer")
    c = role("3", title="Gamma Engineer", location="Sao Paulo")
    d = role("4", title="Delta Engineer")
    seen = {a.key: {"first_seen": "2026-10-20T00:00:00"}, b.key: {"first_seen": "2026-10-26T00:00:00"},
            c.key: {"first_seen": "2026-10-27T00:00:00"}, d.key: {"first_seen": "2026-10-10T00:00:00"}}
    outs = {"3": outcome("BR")}
    rows, _ = build([a, b, c, d], seen, last_viewed=datetime(2026, 10, 15), outcomes=outs)
    assert [r.title for r in rows] == ["Beta Engineer", "Alpha Engineer", "Delta Engineer", "Gamma Engineer"]


def test_skipped_only_match_is_tagged():
    row = {"url": "https://x.test/1", "company": "Acme", "role": "x", "date": "2026-10-01", "status": "skipped"}
    rows, _ = build([role()], tracker=[row])
    assert "in tracker (skipped)" in rows[0].tags and rows[0].new is False


def test_applied_beats_skipped_in_either_order():
    skipped = {"url": "", "company": "Acme", "role": "Frontend Engineer", "date": "2026-09-01", "status": "skipped"}
    applied = dict(skipped, date="2026-10-01", status="applied")
    for tracker in ([skipped, applied], [applied, skipped]):
        assert applied_match(role(), tracker)["status"] == "applied"
        rows, _ = build([role()], tracker=tracker)
        assert "applied on 2026-10-01" in rows[0].tags
        assert not any("skipped" in t for t in rows[0].tags)


def test_applied_across_merged_row_beats_skipped_first_role():
    skipped = {"url": "https://x.test/1", "company": "x", "role": "x", "date": "2026-09-01", "status": "skipped"}
    applied = {"url": "https://x.test/2", "company": "x", "role": "x", "date": "2026-10-01", "status": "applied"}
    roles = [role("1"), role("2", location="Cork, Ireland", description=OTHER)]
    rows, _ = build(roles, tracker=[skipped, applied])
    assert len(rows) == 1 and "applied on 2026-10-01" in rows[0].tags


def test_latest_applied_date_wins():
    old = {"url": "https://x.test/1", "company": "x", "role": "x", "date": "2026-09-01", "status": "applied"}
    new = dict(old, date="2026-10-05", status="interview")
    assert applied_match(role(), [old, new])["date"] == "2026-10-05"


def test_missing_date_tag():
    row = {"url": "https://x.test/1", "company": "x", "role": "x", "date": "", "status": "applied"}
    rows, _ = build([role()], tracker=[row])
    assert "applied (date unknown)" in rows[0].tags


def test_empty_identity_never_matches_by_name():
    row = {"url": "", "company": "", "role": "", "date": "2026-10-01", "status": "applied"}
    assert applied_match(role(company="!!!", title="???"), [row]) is None


def test_clone_clusters_in_two_locations_merge_with_largest_count():
    roles = [role("1"), role("2"), role("3"),
             role("4", location="Cork, Ireland"), role("5", location="Cork, Ireland")]
    rows, flagged = build(roles)
    assert len(rows) == 1 and rows[0].locations == ["Dublin, Ireland", "Cork, Ireland"]
    assert "cloned ×3" in rows[0].tags and flagged == {"Acme Ltd": "cloned"}

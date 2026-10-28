import json
from datetime import date, datetime, timedelta

from cvforge.discover.sources import Role
from cvforge.discover.store import (
    fingerprint,
    flag_ghosts,
    ghost_marked,
    is_stale,
    load_ghosts,
    load_seen,
    norm_title,
    prune_runs,
    read_last_run,
    read_last_viewed,
    save_ghosts,
    save_seen,
    update_seen,
    write_last_run,
    write_last_viewed,
    write_run,
)

NOW = datetime(2026, 10, 28, 23, 5)
GH = {("greenhouse", "acme")}


def role(job_id, board="acme", title="Software Engineer", company="Acme Ltd", description="Build things 24/7"):
    return Role(source="greenhouse", board=board, job_id=job_id, company=company, title=title,
                location="Dublin", workplace=None, url=f"https://x.test/{job_id}",
                description=description, salary=None)


def test_first_seen_kept_across_runs():
    seen = {}
    update_seen(seen, [role("1")], {"greenhouse:acme:1": "IE"}, now=NOW, fetched=GH)
    later = NOW + timedelta(days=1)
    update_seen(seen, [role("1")], {"greenhouse:acme:1": "BR"}, now=later, fetched=GH)
    rec = seen["greenhouse:acme:1"]
    assert rec["first_seen"] == "2026-10-28T23:05:00"
    assert rec["last_seen"] == "2026-10-29T23:05:00"
    assert rec["market"] == "BR"
    assert rec["location"] == "Dublin"
    assert rec["times_reposted"] == 0 and rec["gone_since"] is None


def test_failed_board_does_not_mark_gone():
    seen = {}
    update_seen(seen, [role("1", board="acme")], {}, now=NOW, fetched=GH)
    update_seen(seen, [], {}, now=NOW + timedelta(days=1), fetched=set())
    assert seen["greenhouse:acme:1"]["gone_since"] is None


def test_gone_then_back_counts_repost():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    gone_at = NOW + timedelta(days=1)
    update_seen(seen, [], {}, now=gone_at, fetched=GH)
    assert seen["greenhouse:acme:1"]["gone_since"] == "2026-10-29T23:05:00"
    update_seen(seen, [], {}, now=NOW + timedelta(days=2), fetched=GH)
    assert seen["greenhouse:acme:1"]["gone_since"] == "2026-10-29T23:05:00"
    update_seen(seen, [role("1")], {}, now=NOW + timedelta(days=3), fetched=GH)
    rec = seen["greenhouse:acme:1"]
    assert rec["times_reposted"] == 1 and rec["gone_since"] is None


def test_new_id_same_role_inherits_first_seen():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    old_first_seen = seen["greenhouse:acme:1"]["first_seen"]
    update_seen(seen, [], {}, now=NOW + timedelta(days=1), fetched=GH)
    update_seen(seen, [role("2", title="Software Engineer (m/f/d)", company="ACME")], {},
                now=NOW + timedelta(days=2), fetched=GH)
    rec = seen["greenhouse:acme:2"]
    assert rec["first_seen"] == old_first_seen and rec["times_reposted"] == 1
    assert seen["greenhouse:acme:1"]["gone_since"] is not None


def test_new_id_different_description_is_fresh():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    update_seen(seen, [], {}, now=NOW + timedelta(days=1), fetched=GH)
    update_seen(seen, [role("2", description="Something else")], {}, now=NOW + timedelta(days=2), fetched=GH)
    rec = seen["greenhouse:acme:2"]
    assert rec["first_seen"] == "2026-10-30T23:05:00" and rec["times_reposted"] == 0


def test_new_id_does_not_match_live_record():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    update_seen(seen, [role("1"), role("2")], {}, now=NOW + timedelta(days=1), fetched=GH)
    assert seen["greenhouse:acme:2"]["times_reposted"] == 0


def test_record_fields():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    assert set(seen["greenhouse:acme:1"]) == {
        "key", "source", "board", "job_id", "company", "title", "url", "market", "first_seen",
        "last_seen", "gone_since", "times_reposted", "fingerprint", "location"}
    assert "successor" not in seen["greenhouse:acme:1"]
    assert seen["greenhouse:acme:1"]["market"] is None


def test_is_stale():
    assert not is_stale({"first_seen": "2026-10-14T23:05:00", "times_reposted": 0}, NOW)
    assert is_stale({"first_seen": "2026-10-13T23:05:00", "times_reposted": 0}, NOW)
    assert is_stale({"first_seen": "2026-10-27T23:05:00", "times_reposted": 1}, NOW)


def test_norm_title():
    assert norm_title("Software Engineer (m/f/d)") == norm_title("software  engineer")
    assert norm_title("Software Engineer (f/m/x)") == "software engineer"
    assert norm_title("Développeur, Full-Stack") == "developpeur full stack"


def test_fingerprint_ignores_digits_and_spacing():
    assert fingerprint("Build  things 24/7\nnow") == fingerprint("build things 99/1 now")
    assert fingerprint("a b") != fingerprint("a c")


def test_seen_roundtrip(tmp_path):
    path = tmp_path / "sub" / "seen.json"
    assert load_seen(path) == {}
    save_seen(path, {"k": {"title": "Développeur"}})
    assert load_seen(path) == {"k": {"title": "Développeur"}}
    assert "Développeur" in path.read_text(encoding="utf-8")
    assert list(path.parent.iterdir()) == [path]


def test_ghosts_flag_and_load(tmp_path):
    path = tmp_path / "ghosts.json"
    assert load_ghosts(path) == {}
    ghosts = {}
    flag_ghosts(ghosts, {"Acme Ltd": "stale"}, date(2026, 10, 1))
    flag_ghosts(ghosts, {"Acme Ltd": "cloned"}, date(2026, 10, 20))
    assert ghosts == {"acme": {"name": "Acme Ltd", "last_flagged": "2026-10-20", "reason": "cloned"}}
    save_ghosts(path, ghosts)
    assert load_ghosts(path) == ghosts


def test_ghost_marked_expiry_and_manual():
    today = date(2026, 10, 28)
    auto = {"acme": {"name": "Acme", "last_flagged": "2026-07-30", "reason": "stale"}}
    assert ghost_marked("Acme Ltd", auto, None, today)  # 90 days
    old = {"acme": {"name": "Acme", "last_flagged": "2026-07-29", "reason": "stale"}}
    assert not ghost_marked("Acme Ltd", old, None, today)  # 91 days
    assert not ghost_marked("Globex", auto, None, today)
    assert ghost_marked("Acme", old, {"ghost": {"mark": True, "date": "2026-01-01"}}, today)
    assert not ghost_marked("Acme", auto, {"ghost": {"mark": False, "date": "2026-08-01"}}, today)
    assert not ghost_marked("Acme", auto, {"ghost": {"mark": False, "date": "2026-07-30"}}, today)
    assert ghost_marked("Acme", auto, {"ghost": {"mark": False, "date": "2026-07-01"}}, today)
    assert not ghost_marked("Acme", {}, {"ghost": {"mark": False, "date": "2026-07-01"}}, today)


def test_prune_runs(tmp_path):
    today = date(2026, 10, 28)
    runs = tmp_path / "runs"
    runs.mkdir()
    for name in ("2026-07-30.json", "2026-07-29.json", "notes.json", "2026-07-01.txt"):
        (runs / name).write_text("{}")
    assert prune_runs(tmp_path, today) == 1
    assert sorted(p.name for p in runs.iterdir()) == ["2026-07-01.txt", "2026-07-30.json", "notes.json"]
    assert prune_runs(tmp_path / "missing", today) == 0


def test_write_run_overwrites(tmp_path):
    p = write_run(tmp_path, date(2026, 10, 28), {"n": 1})
    assert p == tmp_path / "runs" / "2026-10-28.json"
    write_run(tmp_path, date(2026, 10, 28), {"n": 2})
    assert json.loads(p.read_text(encoding="utf-8")) == {"n": 2}


def test_last_viewed_roundtrip(tmp_path):
    assert read_last_viewed(tmp_path) is None
    write_last_viewed(tmp_path, NOW)
    assert read_last_viewed(tmp_path) == NOW


def test_last_run_roundtrip(tmp_path):
    assert read_last_run(tmp_path) is None
    write_last_run(tmp_path, {"at": "x"})
    assert read_last_run(tmp_path) == {"at": "x"}


def _gone_one():
    seen = {}
    update_seen(seen, [role("1")], {}, now=NOW, fetched=GH)
    update_seen(seen, [], {}, now=NOW + timedelta(days=1), fetched=GH)
    return seen


def test_gone_record_inherited_once():
    seen = _gone_one()
    update_seen(seen, [role("2")], {}, now=NOW + timedelta(days=2), fetched=GH)
    assert seen["greenhouse:acme:1"]["successor"] == "greenhouse:acme:2"
    later = NOW + timedelta(days=3)
    update_seen(seen, [role("2"), role("3")], {}, now=later, fetched=GH)
    rec = seen["greenhouse:acme:3"]
    assert rec["times_reposted"] == 0 and rec["first_seen"] == "2026-10-31T23:05:00"


def test_repost_chain_counts():
    seen = _gone_one()
    update_seen(seen, [role("2")], {}, now=NOW + timedelta(days=2), fetched=GH)
    update_seen(seen, [], {}, now=NOW + timedelta(days=3), fetched=GH)
    update_seen(seen, [role("3")], {}, now=NOW + timedelta(days=4), fetched=GH)
    rec = seen["greenhouse:acme:3"]
    assert rec["times_reposted"] == 2 and rec["first_seen"] == "2026-10-28T23:05:00"


def test_same_run_clones_only_first_inherits():
    seen = _gone_one()
    update_seen(seen, [role("2"), role("3")], {}, now=NOW + timedelta(days=2), fetched=GH)
    assert seen["greenhouse:acme:2"]["times_reposted"] == 1
    assert seen["greenhouse:acme:3"]["times_reposted"] == 0
    assert seen["greenhouse:acme:3"]["first_seen"] == "2026-10-30T23:05:00"


def test_repost_record_stable_on_next_run():
    seen = _gone_one()
    update_seen(seen, [role("2")], {}, now=NOW + timedelta(days=2), fetched=GH)
    update_seen(seen, [role("2")], {}, now=NOW + timedelta(days=3), fetched=GH)
    assert seen["greenhouse:acme:2"]["times_reposted"] == 1


def test_partial_record_skipped_in_matching():
    seen = {"x": {"key": "x", "gone_since": "2026-10-01T00:00:00"}}
    update_seen(seen, [role("2")], {}, now=NOW, fetched=GH)
    assert seen["greenhouse:acme:2"]["times_reposted"] == 0


def test_ghost_manual_false_without_usable_date():
    today = date(2026, 10, 28)
    auto = {"acme": {"name": "Acme", "last_flagged": "2026-10-01", "reason": "stale"}}
    for manual in ({"mark": False}, {"mark": False, "date": "junk"}):
        assert ghost_marked("Acme", auto, {"ghost": manual}, today)
        assert not ghost_marked("Acme", {}, {"ghost": manual}, today)

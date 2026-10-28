import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from cvforge.apply.http import FetchError
from cvforge.apply.ie_permits import load_permit_table
from cvforge.apply.seed import SEED_NOTE
from cvforge.discover.run import due_lines, run_fetch
from cvforge.discover.screen import DROP_REASONS
from cvforge.discover.sources import board_url
from cvforge.money.rates import Rates

NOW = datetime(2026, 10, 28, 9, 0)
TABLE = load_permit_table(date(2026, 10, 28))[0]
FEEDS = Path(__file__).parent / "fixtures" / "feeds"
ACME_URL = board_url("greenhouse", "acme")
GLOBEX_URL = board_url("ashby", "globex")
HOOLI_URL = board_url("greenhouse", "hooli")
UMBRELLA_URL = board_url("ashby", "umbrella")

HOOLI = json.dumps({"jobs": [{
    "id": 501, "title": "Full Stack Engineer", "absolute_url": "https://boards.greenhouse.io/hooli/jobs/501",
    "location": {"name": "Remote, Brazil"}, "content": "&lt;p&gt;React, TypeScript and Node.js.&lt;/p&gt;",
    "metadata": None}]})
UMBRELLA = json.dumps({"jobs": [{
    "id": "u1", "title": "Software Engineer", "location": "Dublin, Ireland", "secondaryLocations": [],
    "jobUrl": "https://jobs.ashbyhq.com/umbrella/u1", "descriptionHtml": "<p>React and TypeScript.</p>",
    "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR",
                                            "currencyCode": "USD", "minValue": 70000, "maxValue": 90000}]}}]})

ACME = {"name": "Acme", "ats": "greenhouse", "slug": "acme", "sponsor": [], "notes": ""}
GLOBEX = {"name": "Globex", "ats": "ashby", "slug": "globex", "sponsor": [], "notes": SEED_NOTE}
INITECH = {"name": "Initech", "ats": "workday", "careers_url": "https://initech.example.com/careers",
           "sponsor": [], "notes": ""}
REGISTRY = [ACME, GLOBEX, INITECH]


class Server:
    def __init__(self, fail=()):
        self.pages = {ACME_URL: (FEEDS / "greenhouse_board.json").read_text(encoding="utf-8"),
                      GLOBEX_URL: (FEEDS / "ashby_board.json").read_text(encoding="utf-8"),
                      HOOLI_URL: HOOLI, UMBRELLA_URL: UMBRELLA}
        self.fail = set(fail)
        self.calls: list[str] = []

    def __call__(self, url, **_):
        self.calls.append(url)
        if url in self.fail or url not in self.pages:
            raise FetchError(f"HTTP 503 for {url}")
        return self.pages[url]


def no_rates():
    raise AssertionError("rates should not be loaded")


def fetch(jobs_dir, master, *, get=None, registry=REGISTRY, rates=no_rates, now=NOW, **kw):
    return run_fetch(jobs_dir, master=master, registry=registry, tracker_rows=kw.pop("tracker_rows", []),
                     table=TABLE, rates=rates, get=get or Server(), now=now, pause=0, **kw)


def test_run_writes_files_and_counts(tmp_path, discover_master):
    rendered = []

    def render(result, viewed):
        rendered.append((result, viewed))
        return "<html>jobs</html>"

    result = fetch(tmp_path, discover_master, render=render)
    assert (tmp_path / "seen.json").exists()
    assert (tmp_path / "ghosts.json").exists()
    run = json.loads((tmp_path / "runs" / "2026-10-28T0900.json").read_text(encoding="utf-8"))
    keys = {r["key"]: r for r in run["roles"]}
    assert set(keys) == {"greenhouse:acme:101", "greenhouse:acme:102", "greenhouse:acme:103",
                         "ashby:globex:a1", "ashby:globex:a2"}
    assert keys["ashby:globex:a2"]["drop"] == "out-of-market"
    assert keys["greenhouse:acme:101"]["drop"] is None
    assert all("description" not in r for r in run["roles"])
    assert run["at"] == "2026-10-28T09:00:00"
    assert set(result.dropped) == set(DROP_REASONS)
    assert result.dropped["out-of-market"] == 2
    assert run["dropped"] == result.dropped
    assert result.fetched == 5 and result.boards == 2 and result.failed == 0 and result.errors == []
    assert result.now == NOW
    assert result.manual == [{"name": "Initech", "ats": "workday",
                              "careers_url": "https://initech.example.com/careers"}]
    assert {(r.company, r.title) for r in result.rows} == {
        ("Acme", "Full Stack Engineer"), ("Acme", "Data Engineer"), ("Globex", "Backend Engineer")}

    last = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert last["boards"] == 2 and last["failed"] == 0 and last["dropped"] == result.dropped
    backend = next(r for r in last["rows"] if r["title"] == "Backend Engineer")
    assert backend == {"market": "IE", "company": "Globex", "title": "Backend Engineer",
                       "locations": ["Dublin, Ireland; Cork, Ireland"],
                       "url": "https://jobs.ashbyhq.com/globex/a1", "fit": "partial", "tags": ["partial"],
                       "first_seen": "2026-10-28T09:00:00", "tagged": False, "applied": None}
    assert (tmp_path / "latest.html").read_text(encoding="utf-8") == "<html>jobs</html>"
    assert rendered == [(result, None)]


def test_no_render_writes_no_page(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    assert not (tmp_path / "latest.html").exists()


def test_applied_and_sponsor_rows_in_last_run(tmp_path, discover_master):
    registry = [{**ACME, "sponsor": [{"type": "ie-permit", "source": "dete", "date": "2026-01-01"}]}]
    tracker = [{"company": "Acme", "role": "Full Stack Engineer", "url": "", "date": "2026-10-20",
                "status": "applied"}]
    fetch(tmp_path, discover_master, registry=registry, tracker_rows=tracker)
    rows = {r["title"]: r for r in json.loads((tmp_path / "last_run.json").read_text())["rows"]}
    assert rows["Full Stack Engineer"]["applied"] == {"date": "2026-10-20", "status": "applied"}
    assert "applied on 2026-10-20" in rows["Full Stack Engineer"]["tags"]
    assert rows["Full Stack Engineer"]["tagged"] is False
    assert "sponsor" in rows["Data Engineer"]["tags"]
    assert rows["Data Engineer"]["tagged"] is False  # only ghost signs count as tagged


def test_stale_row_is_tagged_in_last_run(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    fetch(tmp_path, discover_master, now=NOW + timedelta(days=15))
    rows = json.loads((tmp_path / "last_run.json").read_text())["rows"]
    assert rows and all("stale" in r["tags"] and r["tagged"] is True for r in rows)


def test_all_failed_run_keeps_the_list(tmp_path, discover_master):
    fetch(tmp_path, discover_master, render=lambda r, v: "<html>good</html>")
    before = json.loads((tmp_path / "last_run.json").read_text())
    assert before["rows"]
    later = NOW + timedelta(days=1)
    result = fetch(tmp_path, discover_master, get=Server(fail={ACME_URL, GLOBEX_URL}), now=later,
                   render=lambda r, v: "<html>empty</html>")
    assert result.all_failed
    last = json.loads((tmp_path / "last_run.json").read_text())
    assert last["rows"] == before["rows"]
    assert last["at"] == "2026-10-29T09:00:00"
    assert last["failed"] == last["boards"] == 2 and last["errors"] == result.errors
    assert (tmp_path / "latest.html").read_text() == "<html>good</html>"
    run = json.loads((tmp_path / "runs" / "2026-10-29T0900.json").read_text())
    assert run["errors"] == result.errors and run["roles"] == []


def test_all_failed_first_run_has_empty_rows(tmp_path, discover_master):
    fetch(tmp_path, discover_master, get=Server(fail={ACME_URL, GLOBEX_URL}))
    assert json.loads((tmp_path / "last_run.json").read_text())["rows"] == []


def test_failed_board_is_reported_and_others_continue(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    for day in (1, 2):
        server = Server(fail={GLOBEX_URL})
        result = fetch(tmp_path, discover_master, get=server, now=NOW + timedelta(days=day))
        assert result.failed == 1 and result.boards == 2 and not result.all_failed
        assert len(result.errors) == 1
        assert result.errors[0].startswith("Globex (ashby): ")
        assert "HTTP 503" in result.errors[0]
        assert {r.company for r in result.rows} == {"Acme"}
        seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
        globex = [rec for rec in seen.values() if rec["board"] == "globex"]
        assert len(globex) == 2
        assert all(rec["gone_since"] is None for rec in globex)
    last = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert last["failed"] == 1 and last["errors"] == result.errors


def test_gone_role_marked_when_its_board_answers(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    server = Server()
    server.pages[GLOBEX_URL] = json.dumps({"jobs": []})
    fetch(tmp_path, discover_master, get=server, now=NOW + timedelta(days=1))
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert seen["ashby:globex:a1"]["gone_since"] == "2026-10-29T09:00:00"
    assert seen["greenhouse:acme:101"]["gone_since"] is None


def test_all_failed(tmp_path, discover_master):
    result = fetch(tmp_path, discover_master, get=Server(fail={ACME_URL, GLOBEX_URL}))
    assert result.all_failed is True
    assert result.failed == 2 and result.rows == [] and result.fetched == 0


def test_no_boards_is_not_all_failed(tmp_path, discover_master):
    result = fetch(tmp_path, discover_master, registry=[INITECH])
    assert result.boards == 0 and result.all_failed is False


def test_dry_run_writes_nothing(tmp_path, discover_master):
    result = fetch(tmp_path / "jobs", discover_master, dry_run=True, render=lambda r, v: "x")
    assert not (tmp_path / "jobs").exists()
    assert len(result.rows) == 3


def test_dry_run_leaves_existing_state_alone(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    before = {p.name: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    server = Server()
    server.pages[GLOBEX_URL] = json.dumps({"jobs": []})
    fetch(tmp_path, discover_master, get=server, now=NOW + timedelta(days=5), dry_run=True)
    after = {p.name: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_market_filter(tmp_path, discover_master):
    registry = [*REGISTRY, {"name": "Hooli", "ats": "greenhouse", "slug": "hooli", "sponsor": [], "notes": ""}]
    server = Server()
    result = fetch(tmp_path, discover_master, registry=registry, get=server, market="BR")
    assert result.rows and {r.market for r in result.rows} == {"BR"}
    assert [r.company for r in result.rows] == ["Hooli"]
    assert server.calls == [ACME_URL, GLOBEX_URL, HOOLI_URL]
    assert result.fetched == 6


def test_market_filter_keeps_state_for_every_market(tmp_path, discover_master):
    clone = {"title": "Frontend Engineer", "location": {"name": "Dublin, Ireland"},
             "content": "&lt;p&gt;React and TypeScript for our shop builder.&lt;/p&gt;", "metadata": None}
    board = json.dumps({"jobs": [{**clone, "id": i, "absolute_url": f"https://boards.greenhouse.io/cloneco/jobs/{i}"}
                                 for i in (1, 2)]})
    server = Server()
    server.pages[board_url("greenhouse", "cloneco")] = board
    registry = [{"name": "Cloneco", "ats": "greenhouse", "slug": "cloneco", "sponsor": [], "notes": ""},
                {"name": "Hooli", "ats": "greenhouse", "slug": "hooli", "sponsor": [], "notes": ""}]
    result = fetch(tmp_path, discover_master, registry=registry, get=server, market="BR")
    assert [r.company for r in result.rows] == ["Hooli"]
    ghosts = json.loads((tmp_path / "ghosts.json").read_text())
    assert [g["name"] for g in ghosts.values()] == ["Cloneco"]
    rows = json.loads((tmp_path / "last_run.json").read_text())["rows"]
    assert {(r["company"], r["market"]) for r in rows} == {("Cloneco", "IE"), ("Hooli", "BR")}
    assert next(r for r in rows if r["company"] == "Cloneco")["tagged"] is True


def test_unknown_market_or_source_is_refused(tmp_path, discover_master):
    with pytest.raises(ValueError):
        fetch(tmp_path, discover_master, market="PT")
    with pytest.raises(ValueError):
        fetch(tmp_path, discover_master, source="indeed")


def test_source_filter_fetches_one_ats(tmp_path, discover_master):
    server = Server()
    result = fetch(tmp_path, discover_master, get=server, source="ashby")
    assert server.calls == [GLOBEX_URL]
    assert result.boards == 1


def test_partial_run_keeps_the_list_and_page(tmp_path, discover_master):
    fetch(tmp_path, discover_master, render=lambda r, v: "<html>full</html>")
    before = (tmp_path / "last_run.json").read_text(encoding="utf-8")
    later = NOW + timedelta(hours=2)
    server = Server()
    result = fetch(tmp_path, discover_master, get=server, source="ashby", now=later,
                   render=lambda r, v: "<html>partial</html>")
    assert server.calls == [GLOBEX_URL]
    assert {r.company for r in result.rows} == {"Globex"}
    assert (tmp_path / "last_run.json").read_text(encoding="utf-8") == before
    assert (tmp_path / "latest.html").read_text(encoding="utf-8") == "<html>full</html>"
    run = json.loads((tmp_path / "runs" / "2026-10-28T1100.json").read_text(encoding="utf-8"))
    assert {r["key"] for r in run["roles"]} == {"ashby:globex:a1", "ashby:globex:a2"}
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert seen["ashby:globex:a1"]["last_seen"] == "2026-10-28T11:00:00"
    assert seen["greenhouse:acme:101"]["last_seen"] == "2026-10-28T09:00:00"
    assert seen["greenhouse:acme:101"]["gone_since"] is None


def test_same_day_runs_keep_both_run_files(tmp_path, discover_master):
    fetch(tmp_path, discover_master)
    fetch(tmp_path, discover_master, now=NOW + timedelta(minutes=30))
    names = sorted(p.name for p in (tmp_path / "runs").iterdir())
    assert names == ["2026-10-28T0900.json", "2026-10-28T0930.json"]


def test_feed_entry_without_slug_is_listed_by_hand(tmp_path, discover_master):
    noslug = {"name": "Noslug", "ats": "greenhouse", "careers_url": "https://noslug.example.com/careers",
              "sponsor": [], "notes": ""}
    server = Server()
    result = fetch(tmp_path, discover_master, registry=[*REGISTRY, noslug], get=server)
    assert server.calls == [ACME_URL, GLOBEX_URL] and result.boards == 2
    assert result.manual == [
        {"name": "Initech", "ats": "workday", "careers_url": "https://initech.example.com/careers"},
        {"name": "Noslug", "ats": "greenhouse", "careers_url": "https://noslug.example.com/careers"}]


def test_gupy_source_fetches_nothing_yet(tmp_path, discover_master):
    server = Server()
    result = fetch(tmp_path, discover_master, get=server, source="gupy")
    assert server.calls == [] and result.boards == 0


def test_pause_between_requests_only(tmp_path, discover_master, monkeypatch):
    sleeps = []
    monkeypatch.setattr("cvforge.discover.run.time.sleep", sleeps.append)
    run_fetch(tmp_path, master=discover_master, registry=REGISTRY, tracker_rows=[], table=TABLE,
              rates=no_rates, get=Server(), now=NOW, pause=1.5)
    assert sleeps == [1.5]


def test_rates_loaded_only_when_needed(tmp_path, discover_master):
    fetch(tmp_path, discover_master, rates=no_rates)  # all-EUR fixtures: no_rates would raise

    calls = []

    def rates():
        calls.append(1)
        return Rates(day="2026-10-28", per_eur={"EUR": 1.0, "USD": 1.1})

    registry = [*REGISTRY, {"name": "Umbrella", "ats": "ashby", "slug": "umbrella", "sponsor": [], "notes": ""}]
    result = fetch(tmp_path / "b", discover_master, registry=registry, rates=rates)
    assert calls == [1]
    umbrella = next(r for r in result.rows if r.company == "Umbrella")
    # USD is converted for the drop gate only; a non-EUR salary never shows a route.
    assert umbrella.route == "unknown" and "salary unknown" in umbrella.tags


def test_rates_failure_means_none(tmp_path, discover_master):
    def broken():
        raise OSError("offline")

    registry = [{"name": "Umbrella", "ats": "ashby", "slug": "umbrella", "sponsor": [], "notes": ""}]
    result = fetch(tmp_path, discover_master, registry=registry, rates=broken)
    assert [r.company for r in result.rows] == ["Umbrella"]
    assert "salary unknown" in result.rows[0].tags


def test_home_market_from_profile_unless_irish_entry(tmp_path, discover_master):
    # Remote roles with no region follow the board's home market.
    board = json.dumps({"jobs": [{"id": 9, "title": "Software Engineer", "absolute_url": "https://x.test/9",
                                  "location": {"name": "Remote"}, "content": "React and TypeScript",
                                  "metadata": None}]})
    url = board_url("greenhouse", "brco")
    server = Server()
    server.pages[url] = board
    master = {**discover_master, "x-preferences": {**discover_master["x-preferences"], "markets": ["BR", "IE"]}}
    plain = {"name": "BrCo", "ats": "greenhouse", "slug": "brco", "sponsor": [], "notes": ""}
    result = fetch(tmp_path / "a", master, registry=[plain], get=server)
    assert [r.market for r in result.rows] == ["BR"]
    seeded = {**plain, "notes": SEED_NOTE}
    result = fetch(tmp_path / "b", master, registry=[seeded], get=server)
    assert [r.market for r in result.rows] == ["IE"]


def write_last_run(jobs_dir, at, rows, failed=0, boards=10):
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "last_run.json").write_text(json.dumps({
        "at": at.isoformat(timespec="seconds"), "boards": boards, "failed": failed, "errors": [],
        "dropped": {}, "rows": rows}), encoding="utf-8")


def due_row(market, first_seen, tagged=False, applied=None):
    return {"market": market, "company": "Acme", "title": "Engineer", "locations": [], "url": "https://x.test",
            "fit": "match", "tags": [], "first_seen": first_seen.isoformat(timespec="seconds"),
            "tagged": tagged, "applied": applied}


def test_due_lines(tmp_path):
    assert due_lines(tmp_path, NOW) == ["jobs: never fetched; run cvforge jobs fetch"]
    at = NOW - timedelta(days=3)
    write_last_run(tmp_path, at, [
        due_row("IE", at, tagged=True), due_row("IE", at),
        due_row("BR", at),
        due_row("IE", at, tagged=True, applied={"date": "2026-10-20", "status": "applied"}),
    ], failed=1, boards=10)
    assert due_lines(tmp_path, NOW) == [
        "jobs: 2 new Irish roles, 1 new Brazilian (1 tagged)",
        "jobs: last run 3 days ago; run cvforge jobs fetch",
        "jobs: 1 of 10 sources failed in the last run",
    ]


def test_due_lines_counts_only_rows_since_last_viewed(tmp_path):
    at = NOW - timedelta(days=2)
    viewed = NOW - timedelta(days=1)
    write_last_run(tmp_path, at, [due_row("IE", viewed - timedelta(hours=1), tagged=True),
                                  due_row("IE", viewed + timedelta(hours=1))])
    (tmp_path / "last_viewed.json").write_text(json.dumps({"at": viewed.isoformat(timespec="seconds")}))
    assert due_lines(tmp_path, NOW) == ["jobs: 1 new Irish roles, 0 new Brazilian (0 tagged)"]

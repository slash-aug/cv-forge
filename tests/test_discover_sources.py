from datetime import date
from pathlib import Path

import pytest

from cvforge.apply import http
from cvforge.discover.sources import SourceError, board_url, fetch_board

FIX = Path(__file__).parent / "fixtures" / "feeds"
TODAY = date(2026, 10, 28)


def fake(routes: dict[str, str]):
    def get(url: str, **_kw) -> str:
        if url not in routes:
            raise http.FetchError(f"no route {url}")
        name = routes[url]
        return (FIX / name).read_text(encoding="utf-8") if name.endswith(".json") else name
    return get


def entry(ats, slug="acme", name="Acme"):
    return {"name": name, "ats": ats, "slug": slug}


def test_greenhouse_board_maps_every_job():
    roles = fetch_board(entry("greenhouse"), get=fake({board_url("greenhouse", "acme"): "greenhouse_board.json"}),
                        today=TODAY)
    assert [r.job_id for r in roles] == ["101", "102", "103"]
    assert roles[0].company == "Acme" and roles[0].location == "Dublin, Ireland"
    assert roles[0].url == "https://boards.greenhouse.io/acme/jobs/101"
    assert "<p>" not in roles[0].description and "React" in roles[0].description
    assert roles[2].location == "" and roles[2].description == ""
    assert roles[0].key == "greenhouse:acme:101"


def test_board_urls():
    assert board_url("greenhouse", "acme") == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    assert board_url("ashby", "acme") == "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true"
    assert board_url("lever", "acme") == "https://api.lever.co/v0/postings/acme?mode=json"
    assert board_url("workable", "acme") == "https://apply.workable.com/api/v1/widget/accounts/acme?details=true"


def test_ashby_salary_is_structured():
    roles = fetch_board(entry("ashby", "globex", "Globex"),
                        get=fake({board_url("ashby", "globex"): "ashby_board.json"}), today=TODAY)
    assert roles[0].salary == {"currency": "EUR", "min": 60000, "max": 80000, "period": "year"}
    assert roles[0].workplace == "remote"
    assert roles[0].location == "Dublin, Ireland; Cork, Ireland"
    assert roles[1].salary is None


def test_lever_and_workable_map():
    lever = fetch_board(entry("lever"), get=fake({board_url("lever", "acme"): "lever_board.json"}), today=TODAY)
    assert lever[0].job_id == "l1" and lever[0].title == "Platform Engineer"
    assert lever[0].location == "Berlin, Germany" and lever[0].workplace == "hybrid"
    assert lever[0].url == "https://jobs.lever.co/acme/l1"
    assert lever[0].salary == {"currency": "EUR", "min": 65000, "max": 85000, "period": "year"}
    assert lever[1].salary is None and lever[1].location == ""
    work = fetch_board(entry("workable"), get=fake({board_url("workable", "acme"): "workable_account.json"}),
                       today=TODAY)
    assert work[0].job_id == "AB12CD" and work[0].location == "Cork, Ireland"
    assert work[0].url == "https://apply.workable.com/acme/j/AB12CD/" and work[0].salary is None
    assert work[1].location == "Portugal" and work[1].workplace == "remote"
    assert work[1].url == "https://apply.workable.com/acme/j/EF34GH/"


def test_bad_json_raises_source_error():
    with pytest.raises(SourceError):
        fetch_board(entry("lever"), get=fake({board_url("lever", "acme"): "<html>"}), today=TODAY)
    with pytest.raises(SourceError):
        fetch_board(entry("ashby"), get=fake({board_url("ashby", "acme"): '{"jobs": 5}'}), today=TODAY)


def test_fetch_error_raises_source_error():
    with pytest.raises(SourceError):
        fetch_board(entry("greenhouse"), get=fake({}), today=TODAY)


def test_one_bad_record_is_skipped():
    body = ('{"jobs": [{"id": 1, "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},'
            '{"title": "No id", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2"},'
            '"junk", null,'
            '{"id": 4, "title": "LinkedIn", "absolute_url": "https://www.linkedin.com/jobs/view/4"},'
            '{"id": 5, "title": "Fine", "absolute_url": "https://boards.greenhouse.io/acme/jobs/5"}]}')
    roles = fetch_board(entry("greenhouse"), get=fake({board_url("greenhouse", "acme"): body}), today=TODAY)
    assert [r.job_id for r in roles] == ["5"]


def test_odd_salary_is_unknown():
    body = ('{"jobs": [{"id": "x", "title": "T", "jobUrl": "https://jobs.ashbyhq.com/a/x", "compensation": '
            '{"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR", '
            '"minValue": "n/a", "maxValue": null}]}}]}')
    roles = fetch_board(entry("ashby"), get=fake({board_url("ashby", "acme"): body}), today=TODAY)
    assert roles[0].salary is None


def test_entry_without_slug_raises_source_error():
    with pytest.raises(SourceError):
        fetch_board({"name": "Acme", "ats": "greenhouse"}, get=fake({}), today=TODAY)
    with pytest.raises(SourceError):
        fetch_board({"name": "Acme", "ats": "gupy", "slug": "acme"}, get=fake({}), today=TODAY)


def test_feed_text_is_cleaned():
    page = ('{"jobs": [{"id": 1, "title": "Dev\\u001b[2J\\u202e", "absolute_url": "https://x.example/1", '
            '"location": {"name": "Dub\\u001b]0;x\\u0007lin"}, "content": ""}]}')
    roles = fetch_board(entry("greenhouse"), get=fake({board_url("greenhouse", "acme"): page}), today=TODAY)
    assert roles[0].title == "Dev [2J"
    assert roles[0].location == "Dub ]0;x lin"

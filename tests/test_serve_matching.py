import pytest

from cvforge.apply.posting import Posting
from cvforge.serve.matching import (
    LinkedInRefused,
    OpenJob,
    match,
    open_jobs,
    site_job_id,
    url_key,
)
from cvforge.track import tracker


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/exampleco/jobs/4012345", ("greenhouse", "4012345")),
    ("https://job-boards.greenhouse.io/exampleco/jobs/4012345?gh_src=x", ("greenhouse", "4012345")),
    ("https://boards.greenhouse.io/embed/job_app?for=exampleco&token=4012345", ("greenhouse", "4012345")),
    ("https://careers.example.com/open-roles?gh_jid=4012345", ("greenhouse", "4012345")),
    ("https://ventania.gupy.io/job/eyJqb2JJZCI6NTU1MDAwMX0=?jobBoardSource=gupy_portal", ("gupy", "5550001")),
    ("https://ventania.gupy.io/job/eyJqb2JJZCI6NTU1MDAwMX0", ("gupy", "5550001")),
    ("https://ventania.gupy.io/job/not-base64", None),
    ("https://examplecorp.gupy.io/jobs/9876543?jobBoardSource=gupy_public_page", ("gupy", "9876543")),
    ("https://login.gupy.io/candidates/jobs/9876543/apply/step-1", ("gupy", "9876543")),
    ("https://jobs.example.com/senior", None),
    ("https://evilgupy.io/jobs/1", None),
    ("https://boards.greenhouse.io/exampleco/jobs/abc", None),
    ("https://careers.example.com/x?gh_jid=abc", None),
])
def test_site_job_id(url, expected):
    assert site_job_id(url) == expected


def job(slug, posting_url, apply_url=None):
    return OpenJob(slug=slug, company="Example Corp", role="Engineer",
                   posting_url=posting_url, apply_url=apply_url)


def test_url_key_normalises():
    assert url_key("https://WWW.Example.com./jobs/1/?utm_source=x#top") == ("example.com", "/jobs/1")


def test_match_by_site_id_beats_url():
    jobs = [job("a", "https://boards.greenhouse.io/exampleco/jobs/4012345"),
            job("b", "https://careers.example.com/open-roles")]
    page = "https://careers.example.com/open-roles?gh_jid=4012345"
    assert match(jobs, page, site="greenhouse", job_id="4012345") == ["a"]


def test_match_site_id_uses_apply_url():
    jobs = [job("a", "https://x.example.com/p", "https://boards.greenhouse.io/exampleco/jobs/77")]
    assert match(jobs, "https://other.example.com/", site="greenhouse", job_id="77") == ["a"]


def test_match_by_path_prefix():
    jobs = [job("a", "https://jobs.example.com/jobs/123"), job("b", "https://jobs.example.com/jobs/1234")]
    assert match(jobs, "https://jobs.example.com/jobs/123/apply") == ["a"]
    assert match(jobs, "https://jobs.example.com/jobs/12") == []


def test_match_by_apply_url():
    jobs = [job("a", "https://jobs.example.com/p/1", "https://apply.example.com/f/1")]
    assert match(jobs, "https://apply.example.com/f/1/step2") == ["a"]


def test_match_ignores_tracking_and_www():
    jobs = [job("a", "https://jobs.example.com/senior")]
    assert match(jobs, "https://www.JOBS.example.com/senior/?utm_medium=x&gh_src=y#f") == ["a"]


def test_match_root_path_does_not_match_everything():
    jobs = [job("a", "https://example.com/")]
    assert match(jobs, "https://example.com/careers/other") == []


def test_match_ambiguous_returns_all():
    jobs = [job("a", "https://jobs.example.com/senior"), job("b", "https://jobs.example.com/senior")]
    assert match(jobs, "https://jobs.example.com/senior") == ["a", "b"]


def test_match_none():
    assert match([job("a", "https://jobs.example.com/senior")], "https://jobs.example.com/junior") == []
    assert match([], "https://jobs.example.com/junior", site="gupy", job_id="1") == []


@pytest.mark.parametrize("url", ["https://www.linkedin.com/jobs/view/1", "https://linkedin.com./jobs/1"])
def test_match_refuses_linkedin(url):
    with pytest.raises(LinkedInRefused):
        match([job("a", "https://jobs.example.com/senior")], url)


def posting(url, apply_url=None):
    return Posting(company="Example Corp", title="Engineer", location="Remote",
                   location_requirements=[], workplace="remote", salary=None, language="en",
                   url=url, apply_url=apply_url, source="test", fetched="2026-10-22",
                   description="A fictional role.")


def test_open_jobs_only_drafted(tmp_path):
    csv = tmp_path / "tracker.csv"
    rows = [("one", "drafted", True), ("two", "applied", True), ("three", "skipped", True),
            ("four", "drafted", False), ("five", "drafted", True)]
    for slug, status, has_posting in rows:
        tracker.upsert(csv, {"slug": slug, "company": f"Co {slug}", "role": f"Role {slug}", "status": status})
        if has_posting:
            posting(f"https://jobs.example.com/{slug}", f"https://apply.example.com/{slug}" if slug == "one" else None
                    ).save(tmp_path / "applications" / slug)
    jobs = open_jobs(tmp_path)
    assert [j.slug for j in jobs] == ["one", "five"]
    assert jobs[0] == OpenJob("one", "Co one", "Role one", "https://jobs.example.com/one",
                              "https://apply.example.com/one")
    assert jobs[1].apply_url is None


def test_open_jobs_no_tracker(tmp_path):
    assert open_jobs(tmp_path) == []

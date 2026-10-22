import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.apply import http as apply_http
from cvforge.apply.check import check, region_class
from cvforge.apply.posting import Posting
from cvforge.money.rates import Rates
from cvforge.track import tracker

TODAY = date(2026, 10, 22)
RATES = Rates("2026-10-21", {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85})
PERSONA = Path(__file__).resolve().parents[1] / "examples" / "persona" / "master.yaml"
SPONSOR = {"name": "Acme", "aliases": [], "sponsor": [
    {"type": "pt-tech-visa", "source": "LinkedIn posts", "date": "2026-10-22"}]}

# 17 months of engineering on 2026-10-22: May 2025 to now.
MASTER = {
    "work": [{"id": "w1", "x-category": "engineering",
              "positions": [{"id": "p1", "startDate": "2025-05", "endDate": None}]},
             {"id": "w2", "x-category": "other",
              "positions": [{"id": "p2", "startDate": "2015-01", "endDate": "2024-12"}]}],
    "languages": [
        {"id": "lang-pt", "language": {"en": "Portuguese", "pt-BR": "Português"},
         "fluency": {"en": "Native", "pt-BR": "Nativo"}},
        {"id": "lang-en", "language": "English", "cefr": "C1",
         "fluency": {"en": "Fluent"}, "x-subscores": {"reading": "C2"}},
    ],
    "x-preferences": {"markets": ["BR"], "relocation": True, "visa": {},
                      "payFloor": {"amount": 3000, "currency": "BRL", "period": "month"}},
}


def posting(**over):
    data = {"company": "Acme", "title": "Frontend Engineer", "location": "",
            "location_requirements": [], "workplace": None, "salary": None, "language": "en",
            "url": "https://jobs.example/1", "apply_url": None, "source": "paste",
            "fetched": "2026-10-22", "description": ""}
    data.update(over)
    return Posting(**data)


def req(*, workplace="remote", allowed=(), countries=(), sponsorship="silent", years=None,
        salary=None, languages=()):
    return {
        "years": years or [],
        "location": {"workplace": workplace, "job_countries": list(countries),
                     "allowed": list(allowed), "quote": "Location quote."},
        "sponsorship": {"status": sponsorship,
                        "quote": None if sponsorship == "silent" else "Sponsorship quote."},
        "salary": salary or {"min": None, "max": None, "currency": None, "period": None,
                             "contract": "unknown", "quote": None},
        "languages_required": list(languages),
    }


def _years(n):
    return [{"min": n, "kind": "required", "quote": f"{n}+ years of experience"},
            {"min": 8, "kind": "preferred", "quote": "8 years is a plus"}]


def _salary(lo, hi, cur, period, contract="unknown"):
    return {"min": lo, "max": hi, "currency": cur, "period": period, "contract": contract,
            "quote": "Salary quote."}


CASES = [
    ("remote-europe-silent", req(allowed=["Europe"]), None, "skip", {"location"}),
    ("remote-ca-pl-uk", req(allowed=["Canada", "Poland", "United Kingdom"]), None, "skip",
     {"location"}),
    ("5plus-17-months", req(allowed=["worldwide"], years=_years(5)), None, "skip", {"years"}),
    ("3plus-17-months-worldwide", req(allowed=["worldwide"], years=_years(3)), None, "pass", set()),
    ("hybrid-lisbon", req(workplace="hybrid", countries=["PT"]), None, "pass", set()),
    ("onsite-sao-paulo", req(workplace="onsite", countries=["BR"]), None, "pass", set()),
    ("onsite-de-sponsor", req(workplace="onsite", countries=["DE"]), SPONSOR, "pass", set()),
    ("remote-europe-sponsor", req(allowed=["Europe"]), SPONSOR, "skip", {"location"}),
    ("hybrid-de-refused", req(workplace="hybrid", countries=["DE"], sponsorship="refused"),
     SPONSOR, "skip", {"location"}),
    ("onsite-nl-offered", req(workplace="onsite", countries=["NL"], sponsorship="offered"),
     None, "pass", set()),
    ("remote-americas", req(allowed=["Americas"]), None, "pass", set()),
    # The brief's row reads "1000 USD/month, floor 3000 BRL", but at ECB rates 1000 USD is
    # about 5500 BRL, above that floor. The case keeps its intent (a salary under the floor):
    ("salary-under-floor", req(allowed=["worldwide"], salary=_salary(None, 500, "USD", "month")),
     None, "skip", {"salary"}),
    ("salary-gbp-year", req(allowed=["worldwide"],
                            salary=_salary(75000, 104000, "GBP", "year")), None, "pass", set()),
    ("german-required", req(allowed=["worldwide"], languages=[
        {"lang": "de", "level": "B2", "quote": "Fluent German"}]), None, "pass", set()),
]


@pytest.mark.parametrize("case,requirements,company,expect,failing", CASES,
                         ids=[c[0] for c in CASES])
def test_batch_verdicts(case, requirements, company, expect, failing):
    v = check(requirements, posting(), MASTER, company, RATES, TODAY, clt_factor=1.4)
    assert ("pass" if v.passed else "skip") == expect, [r.message for r in v.results]
    assert {r.rule for r in v.results if not r.ok} == failing
    assert [r.rule for r in v.results] == ["years", "location", "salary", "languages"]
    if case == "german-required":
        assert v.warnings == ["German B2 required; you have English (C1)"]
    else:
        assert v.warnings == []


def test_rule_quotes_and_messages():
    v = check(req(allowed=["Europe"], years=_years(5)), posting(), MASTER, None, RATES, TODAY,
              clt_factor=1.4)
    years, location, salary, languages = v.results
    assert not years.ok and years.quote == "5+ years of experience"
    assert "limit 3" in years.message
    assert not location.ok and location.quote == "Location quote."
    assert salary.ok and salary.quote is None
    assert languages.ok


def test_no_years_stated():
    v = check(req(allowed=["worldwide"], years=[{"min": 9, "kind": "preferred", "quote": "q"}]),
              posting(), MASTER, None, RATES, TODAY, clt_factor=1.4)
    assert v.results[0].ok and v.results[0].message == "no years stated"


def _refused(quote, **kw):
    r = req(sponsorship="refused", **kw)
    r["sponsorship"]["quote"] = quote
    return r


@pytest.mark.parametrize("quote,kw", [
    ("Must reside in Brazil", {"allowed": ["Brazil"]}),
    ("Must reside in Brazil", {}),
    ("Necess\u00e1rio residir no Brasil.", {"allowed": ["Brasil"]}),
    ("Candidates must have the right to work in Portugal.",
     {"workplace": "hybrid", "countries": ["PT"]}),
])
def test_residence_in_home_country_passes(quote, kw):
    v = check(_refused(quote, **kw), posting(), MASTER, None, RATES, TODAY, clt_factor=1.4)
    assert v.passed, [r.message for r in v.results]


@pytest.mark.parametrize("quote,kw", [
    ("Candidates must have the right to work in the EU.", {"allowed": ["Europe"]}),
    ("Must have the right to work in the EU.", {"allowed": ["Brazil"]}),
    ("We do not offer visa sponsorship.", {"workplace": "onsite", "countries": ["DE"]}),
])
def test_residence_elsewhere_skips(quote, kw):
    v = check(_refused(quote, **kw), posting(), MASTER, SPONSOR, RATES, TODAY, clt_factor=1.4)
    assert not v.passed and v.results[1].quote == quote


def test_remote_empty_allowed_needs_sponsor_mark():
    r = req(allowed=[])
    assert not check(r, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4).passed
    assert check(r, posting(), MASTER, SPONSOR, RATES, TODAY, clt_factor=1.4).passed


def test_remote_allowed_portugal_passes():
    assert check(req(allowed=["Portugal", "Spain"]), posting(), MASTER, None, RATES, TODAY,
                 clt_factor=1.4).passed


def test_salary_only_minimum_is_used():
    r = req(allowed=["worldwide"], salary=_salary(400, None, "USD", "month"))
    assert not check(r, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4).passed


def test_salary_clt_factor_applied():
    # 2500 BRL CLT is 3500 BRL as PJ, above a 3000 BRL floor; as PJ it is below.
    clt = req(allowed=["worldwide"], salary=_salary(None, 2500, "BRL", "month", "CLT"))
    pj = req(allowed=["worldwide"], salary=_salary(None, 2500, "BRL", "month", "pj"))
    assert check(clt, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4).passed
    assert not check(pj, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4).passed


def test_language_warnings():
    langs = [{"lang": "es", "quote": "Spanish"}, {"lang": "en", "level": "C2", "quote": "English"},
             {"lang": "Portuguese", "level": "C2", "quote": "Portuguese"},
             {"lang": "en", "level": "B2", "quote": "English B2"},
             {"lang": "English (written)", "quote": "Written English"}]
    v = check(req(allowed=["worldwide"], languages=langs), posting(), MASTER, None, RATES, TODAY,
              clt_factor=1.4)
    assert v.passed
    assert v.warnings == ["Spanish required; you have Portuguese (native)",
                          "English C2 required; you have English (C1)"]


@pytest.mark.parametrize("token,expected", [
    ("BR", "brazil"), ("Brasil", "brazil"), ("pt", "portugal"), ("Portugal", "portugal"),
    ("LATAM", "latam"), ("Latin America", "latam"), ("South  America", "latam"),
    ("Americas", "latam"), ("South and Central America", "latam"), ("Worldwide", "worldwide"),
    ("anywhere", "worldwide"), ("Global", "worldwide"), ("Remote (Global)", "worldwide"),
    ("International", "worldwide"), ("Europe", "other"), ("DE", "other"), ("North America", "other"),
])
def test_region_class(token, expected):
    assert region_class(token) == expected


# CLI


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)

    def no_net(url, **kw):
        raise apply_http.FetchError("network must not be used")

    monkeypatch.setattr(apply_http, "get", no_net)
    (tmp_path / "salary").mkdir()
    (tmp_path / "salary" / f"ecb-{TODAY.isoformat()}.json").write_text(
        json.dumps({"day": RATES.day, "per_eur": RATES.per_eur}), encoding="utf-8")
    return tmp_path


DESCRIPTION = ("Senior Engineer. 5+ years of experience required.\n"
               "Fully remote, Europe only. We pay 9000 EUR per month.")


def _app(data_dir, requirements, slug="acme-senior-engineer"):
    app = data_dir / "applications" / slug
    posting(description=DESCRIPTION).save(app)
    (app / "requirements.yaml").write_text(yaml.safe_dump(requirements), encoding="utf-8")
    tracker.upsert(data_dir / "tracker.csv",
                   {"slug": slug, "company": "Acme", "role": "Senior Engineer",
                    "date": "2026-10-21", "status": "drafted"})
    return app


def _cli_req(allowed):
    r = req(allowed=allowed, years=[{"min": 5, "kind": "required",
                                     "quote": "5+ years of experience required."}],
            salary=_salary(None, 9000, "EUR", "month"))
    r["salary"]["quote"] = "We pay 9000 EUR per month."
    r["location"]["quote"] = "Fully remote, Europe only."
    return r


def _run(*args):
    return cli.main(["check", "acme-senior-engineer", "--master", str(PERSONA), *args])


def test_skip_writes_tracker(env, capsys):
    app = _app(env, _cli_req(["Europe"]))
    assert _run() == 2
    out = capsys.readouterr().out
    assert "PASS years: " in out
    assert "SKIP location: " in out
    assert '    "Fully remote, Europe only."' in out
    row = tracker.load(env / "tracker.csv")[0]
    assert row["status"] == "skipped"
    assert row["skip_reason"].startswith("location: ")
    verdict = json.loads((app / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "skip"
    assert [r["rule"] for r in verdict["results"]] == ["years", "location", "salary", "languages"]


def test_override_passes_and_notes(env, capsys):
    app = _app(env, _cli_req(["Europe"]))
    assert _run("--override", "referral from a friend") == 0
    row = tracker.load(env / "tracker.csv")[0]
    assert row["status"] == "drafted"
    assert row["notes"] == "override: referral from a friend"
    verdict = json.loads((app / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "pass"
    assert verdict["override"] == "referral from a friend"


def test_cli_pass(env, capsys):
    app = _app(env, _cli_req(["worldwide"]))
    assert _run() == 0
    assert tracker.load(env / "tracker.csv")[0]["status"] == "drafted"
    assert json.loads((app / "verdict.json").read_text(encoding="utf-8"))["verdict"] == "pass"


def test_cli_quote_problems_exit_1(env, capsys):
    bad = copy.deepcopy(_cli_req(["worldwide"]))
    bad["location"]["quote"] = "Fully remote, worldwide."
    app = _app(env, bad)
    assert _run() == 1
    assert "location.quote" in capsys.readouterr().out
    verdict = json.loads((app / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "invalid"
    assert tracker.load(env / "tracker.csv")[0]["status"] == "drafted"


def test_cli_unknown_slug(env, capsys):
    assert cli.main(["check", "nope", "--master", str(PERSONA)]) == 1


def _rewrite(app, requirements):
    (app / "requirements.yaml").write_text(yaml.safe_dump(requirements), encoding="utf-8")


def test_pass_after_skip_resets_row(env, capsys):
    app = _app(env, _cli_req(["Europe"]))
    assert _run() == 2
    _rewrite(app, _cli_req(["worldwide"]))
    assert _run() == 0
    row = tracker.load(env / "tracker.csv")[0]
    assert (row["status"], row["skip_reason"]) == ("drafted", "")


def test_override_after_skip_clears_skip_reason(env, capsys):
    _app(env, _cli_req(["Europe"]))
    assert _run() == 2
    assert _run("--override", "referral") == 0
    row = tracker.load(env / "tracker.csv")[0]
    assert (row["status"], row["skip_reason"]) == ("drafted", "")


def test_pass_keeps_later_status(env, capsys):
    _app(env, _cli_req(["worldwide"]))
    tracker.set_status(env / "tracker.csv", "acme-senior-engineer", "applied", TODAY)
    assert _run() == 0
    assert tracker.load(env / "tracker.csv")[0]["status"] == "applied"

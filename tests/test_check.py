import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.apply import http as apply_http
from cvforge.apply.check import (
    CAVEAT_TERMS,
    caveat_sentences,
    check,
    home_regions,
    is_irish_job,
    region_class,
    uncaptured_caveats,
)
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


def test_remote_with_no_region_passes_without_sponsor_mark():
    # No region stated usually means no work visa is needed, so it is always worth applying.
    v = check(req(allowed=[]), posting(), MASTER, None, RATES, TODAY, clt_factor=1.4)
    assert v.passed and v.results[1].message == "remote with no region stated"


def test_remote_limited_elsewhere_still_skips():
    v = check(req(allowed=["United States"]), posting(), MASTER, None, RATES, TODAY,
              clt_factor=1.4)
    assert not v.passed and v.results[1].message == "remote limited to United States"


def test_onsite_abroad_still_needs_sponsor_mark():
    r = req(workplace="onsite", countries=["DE"])
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


def test_unpublished_currency_passes_with_warning():
    r = req(allowed=["worldwide"], salary=_salary(900000, 1200000, "ARS", "month"))
    v = check(r, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4)
    assert v.passed
    salary = v.results[2]
    assert salary.ok and "no exchange rate for ARS" in salary.message
    assert v.warnings == ["no exchange rate for ARS: salary not checked against the pay floor"]


def test_cli_unpublished_currency_exit_0(env, capsys):
    r = _cli_req(["worldwide"])
    r["years"] = []
    r["salary"]["currency"] = "ARS"
    _app(env, r)
    assert _run() == 0
    assert "warning: no exchange rate for ARS" in capsys.readouterr().out


# Caveats

def test_caveat_sentences_finds_terms_en_pt():
    text = ("We build payments. Must reside in the EU.\nViagens ocasionais.\n"
            "Great snacks! Is a 4 hour Time   Zone overlap needed?")
    assert caveat_sentences(text) == [
        "Must reside in the EU", "Viagens ocasionais", "Is a 4 hour Time   Zone overlap needed"]
    assert caveat_sentences("Must reside in the EU. Must reside in the EU.") == [
        "Must reside in the EU"]
    assert "pj" in CAVEAT_TERMS and "time zone" in CAVEAT_TERMS


def test_term_prefix_not_substring():
    assert caveat_sentences("Contrato PJ") == ["Contrato PJ"]
    assert caveat_sentences("We use pjax and the theory of travail") == []
    assert caveat_sentences("Autorização de trabalho") == ["Autorização de trabalho"]
    assert caveat_sentences("Fuso horário") == ["Fuso horário"]


def test_uncaptured_caveat_warns():
    text = "Must reside in the EU.\nOccasional travel."
    r = req(allowed=["worldwide"])
    r["location"]["quote"] = "Must reside in the EU."
    assert uncaptured_caveats(r, text) == ["Occasional travel"]


def test_captured_caveat_silent():
    text = "Must reside in the EU.\nOccasional travel to Berlin."
    r = req(allowed=["worldwide"])
    r["location"]["quote"] = "Must   reside in the EU."
    r["travel"] = {"requirement": "occasional", "quote": "Occasional travel to Berlin. And more"}
    assert uncaptured_caveats(r, text) == []


def test_hiring_model_eor_treated_as_clt_for_floor():
    salary = _salary(None, 2000, "EUR", "month")  # 12000 BRL as PJ, 12000 x 0.5 as CLT
    base = req(allowed=["worldwide"], salary=salary)
    floor = {"x-preferences": {"payFloor": {"amount": 10000, "currency": "BRL",
                                            "period": "month"}}}
    master = {**MASTER, **floor}

    def run(model):
        r = copy.deepcopy(base)
        if model:
            r["hiring_model"] = {"type": model, "quote": "q"}
        return check(r, posting(), master, None, RATES, TODAY, clt_factor=0.5)

    assert run(None).passed
    assert run("contractor").passed
    assert not run("eor").passed
    assert "CLT" in run("eor").results[2].message
    r = copy.deepcopy(base)
    r["salary"]["contract"] = "pj"
    r["hiring_model"] = {"type": "eor", "quote": "q"}
    assert check(r, posting(), master, None, RATES, TODAY, clt_factor=0.5).passed


def test_timezone_and_travel_never_skip(env, capsys):
    desc = ("Senior Engineer. 5+ years of experience required.\n"
            "Fully remote, worldwide. We pay 9000 EUR per month.\n"
            "Hired through an Employer of Record. 4 hours overlap with ET. Up to 10% travel.\n"
            "You must be eligible to work here.")
    data = _cli_req(["worldwide"])
    data["location"]["quote"] = "Fully remote, worldwide."
    data["hiring_model"] = {"type": "eor", "quote": "Hired through an Employer of Record."}
    data["timezone"] = {"requirement": "4 hours overlap with ET",
                        "quote": "4 hours overlap with ET."}
    data["travel"] = {"requirement": "up to 10% travel", "quote": "Up to 10% travel."}
    app = env / "applications" / "acme-senior-engineer"
    posting(description=desc).save(app)
    _rewrite(app, data)
    tracker.upsert(env / "tracker.csv", {"slug": "acme-senior-engineer", "company": "Acme",
                                         "role": "x", "date": "2026-10-21",
                                         "status": "drafted"})
    assert _run() == 0
    out = capsys.readouterr().out
    assert 'INFO hiring model: eor\n    "Hired through an Employer of Record."' in out
    assert "INFO time zone: 4 hours overlap with ET" in out
    assert "INFO travel: up to 10% travel" in out
    assert 'WARN uncaptured: "You must be eligible to work here"' in out
    assert out.index("PASS languages") < out.index("INFO hiring model")
    assert out.rstrip().endswith("verdict: pass")
    v = json.loads((app / "verdict.json").read_text(encoding="utf-8"))
    assert v["caveats"]["hiring_model"]["type"] == "eor"
    assert v["caveats"]["timezone"]["requirement"] == "4 hours overlap with ET"
    assert v["caveats"]["travel"]["requirement"] == "up to 10% travel"
    assert v["caveats"]["uncaptured"] == ["You must be eligible to work here"]


def test_caveat_scan_catches_elegivel_and_residencia():
    text = "Você é elegível para a vaga. Residência em Portugal é obrigatória."
    assert caveat_sentences(text) == [
        "Você é elegível para a vaga", "Residência em Portugal é obrigatória"]


def test_ireland_and_eu_tokens():
    assert region_class("Dublin") == "ireland" and region_class("EEA") == "eu"


def test_home_unchanged_for_existing_masters():
    assert home_regions(MASTER) == {"brazil", "portugal"}


def test_home_follows_work_rights():
    master = {"x-preferences": {"workRights": {"IE": {"status": "stamp4"},
                                               "BR": {"status": "citizen"}}}}
    assert home_regions(master) == {"ireland", "brazil"}
    v = check(req(workplace="hybrid", countries=["Dublin"]), posting(), master, None, None,
              TODAY, clt_factor=1.4)
    assert v.results[1].ok and "Brazil or Ireland" in v.results[1].message


def test_remote_eu_only_still_skips_for_non_irish_employer():
    v = check(req(allowed=["EU"]), posting(), MASTER, None, None, TODAY, clt_factor=1.4)
    assert not v.passed and "remote limited to EU" in v.results[1].message


def test_is_irish_job():
    assert is_irish_job(req(workplace="hybrid", countries=["Ireland"]))
    assert is_irish_job(req(allowed=["Ireland"]))
    assert not is_irish_job(req(allowed=["Ireland", "UK"]))


def test_stamp_sentence_is_a_caveat():
    assert caveat_sentences("Great team. Applicants must hold Stamp 4.") == [
        "Applicants must hold Stamp 4"]

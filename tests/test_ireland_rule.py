import copy
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.apply import http as apply_http
from cvforge.apply.check import check
from cvforge.apply.ie_permits import load_permit_table
from cvforge.apply.ireland import route_for
from cvforge.apply.posting import Posting
from cvforge.money.rates import Rates
from cvforge.track import tracker

TODAY = date(2026, 10, 22)
RATES = Rates("2026-10-21", {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85})
PERSONA = Path(__file__).resolve().parents[1] / "examples" / "persona" / "master.yaml"
MASTER = {
    "work": [{"id": "w1", "x-category": "engineering",
              "positions": [{"id": "p1", "startDate": "2025-05", "endDate": None}]}],
    "languages": [{"id": "lang-en", "language": "English", "cefr": "C1",
                   "fluency": {"en": "Fluent"}}],
    "x-preferences": {"markets": ["BR"], "relocation": True, "visa": {},
                      "payFloor": {"amount": 3000, "currency": "BRL", "period": "month"}},
}


def posting(**over):
    data = {"company": "Acme", "title": "Senior Engineer", "location": "",
            "location_requirements": [], "workplace": None, "salary": None, "language": "en",
            "url": "https://jobs.example/1", "apply_url": None, "source": "paste",
            "fetched": "2026-10-22", "description": ""}
    data.update(over)
    return Posting(**data)


def req(*, workplace="remote", countries=(), sponsorship="silent"):
    return {
        "years": [],
        "location": {"workplace": workplace, "job_countries": list(countries), "allowed": [],
                     "quote": "Location quote."},
        "sponsorship": {"status": sponsorship,
                        "quote": None if sponsorship == "silent" else "Sponsorship quote."},
        "salary": {"min": None, "max": None, "currency": None, "period": None,
                   "contract": "unknown", "quote": None},
        "languages_required": [],
    }


TABLE, _ = load_permit_table(TODAY)

IE_MASTER = {**MASTER,
             "education": [{"id": "edu-1", "studyType": {"en": "Associate Degree",
                                                         "pt-BR": "Tecnólogo"}}],
             "certificates": [{"id": "cert-efset",
                               "name": "EF SET English Certificate, C1 Advanced (67/100)"}],
             "x-preferences": {**MASTER["x-preferences"], "markets": ["IE", "BR"],
                               "workRights": {"BR": {"status": "citizen"},
                                              "PT": {"status": "mobility"},
                                              "IE": {"status": "needs-permit",
                                                     "degreeRecognised": "unknown"}}}}
IE_MASTER["x-preferences"].pop("payFloor")


def _degree(value):
    m = copy.deepcopy(IE_MASTER)
    m["x-preferences"]["workRights"]["IE"]["degreeRecognised"] = value
    return m


def ie_req(*, salary=55000, lo=None, currency="EUR", period="year", soc="2136",
           work_authorisation=None, contract=None, english_test=None, degree=None,
           sponsorship="silent", hiring_model=None, countries=("Ireland",)):
    r = req(workplace="hybrid", countries=countries, sponsorship=sponsorship)
    r["location"]["quote"] = "Hybrid, Dublin."
    if salary is not None or lo is not None:
        r["salary"] = {"min": lo, "max": salary, "currency": currency, "period": period,
                       "contract": "unknown", "quote": "Salary quote."}
    if soc:
        r["occupation_soc"] = {"code": soc, "reason": "software engineer"}
    if work_authorisation:
        r["work_authorisation"] = {"status": work_authorisation[0],
                                   "quote": work_authorisation[1]}
    if contract:
        r["contract"] = {"type": contract[0], "months": contract[1], "quote": "Contract quote."}
    if english_test:
        r["english_test"] = {"tests": list(english_test), "level": None, "quote": "IELTS 7."}
    if degree:
        r["degree"] = {"requirement": degree, "quote": "Degree quote."}
    if hiring_model:
        r["hiring_model"] = {"type": hiring_model, "quote": "Hiring quote."}
    return r


def v(master=IE_MASTER, rates=RATES, record=None, dete_imported=True, **over):
    return check(ie_req(**over), posting(), master, None, rates, TODAY, clt_factor=1.4,
                 record=record, table=TABLE, dete_imported=dete_imported)


def permit(verdict):
    return next(r for r in verdict.results if r.rule == "permit")


# Skips


def test_stamp4_only_skips():
    r = v(work_authorisation=("required-without-sponsorship", "Must have Stamp 4."))
    assert not r.passed
    assert permit(r).message == "needs Irish/EU work rights without sponsorship"
    assert permit(r).quote == "Must have Stamp 4."


def test_eu_only_skips():
    assert not v(work_authorisation=("eu-only", "EU citizens only.")).passed


def test_sponsorship_refused_skips():
    r = v(sponsorship="refused")
    assert not r.passed and permit(r).message.startswith("needs Irish/EU work rights")


def test_contractor_skips():
    r = v(contract=("contractor", None))
    assert not r.passed
    assert permit(r).message == "contractor role; no Irish employer to hold a permit"


def test_contractor_through_eor_passes():
    assert v(contract=("contractor", None), hiring_model="eor").passed


def test_fixed_term_9_months_skips():
    r = v(contract=("fixed-term", 9))
    assert not r.passed and permit(r).message == "fixed term under 12 months"


def test_salary_below_gep_skips():
    r = v(salary=35000)
    assert not r.passed
    assert permit(r).message == "salary 35,000 below the GEP floor 36,605"


# Routes


def test_csol_degree_unknown_is_pass_with_risk():
    r = v(salary=55000)
    assert r.passed and r.ireland["route"] == "csep-if-degree"
    assert r.risks[0].startswith("CSEP only if the Tecnólogo is recognised")
    assert r.ireland["on_csol"] and r.ireland["soc"] == "2136"
    assert r.ireland["salary_eur_year"] == 55000 and not r.ireland["lmnt"]


def test_degree_unknown_never_claims_csep_under_68911():
    for s in (40904, 50000, 68910):
        assert v(salary=s).ireland["route"] != "csep"


def test_above_68911_is_plain_csep():
    r = v(salary=70000)
    assert r.passed and r.ireland["route"] == "csep"
    assert not any("Tecnólogo" in x or "GEP" in x for x in r.risks)


def test_degree_yes_is_csep_on_csol():
    assert v(master=_degree("yes"), salary=45000).ireland["route"] == "csep"


def test_degree_no_is_gep_without_lmnt_on_csol():
    r = v(master=_degree("no"), salary=50000)
    assert r.ireland["route"] == "gep" and not r.ireland["lmnt"]
    assert "GEP only" in r.risks


def test_non_csol_soc_mentions_lmnt():
    r = v(soc="3131", salary=50000)
    assert r.passed and r.ireland["route"] == "gep" and r.ireland["lmnt"]
    assert "GEP only; needs a labour market test" in r.risks


def test_csol_under_degree_floor_is_gep():
    r = v(salary=38000)
    assert r.ireland["route"] == "gep" and "GEP only" in r.risks


def test_fixed_term_18_months_forces_gep():
    r = v(salary=70000, contract=("fixed-term", 18))
    assert r.passed and r.ireland["route"] == "gep"
    assert "fixed term under 2 years: GEP only" in r.risks


def test_route_for():
    assert route_for(None, "2136", "unknown", TABLE) == "unknown"
    assert route_for(70000, "3131", "no", TABLE) == "csep"
    assert route_for(50000, "2136", "yes", TABLE) == "csep"
    assert route_for(50000, "2136", "unknown", TABLE) == "csep-if-degree"
    assert route_for(50000, "2136", "no", TABLE) == "gep"
    assert route_for(50000, None, "yes", TABLE) == "gep"


# Sponsorship evidence


def test_silent_without_record_adds_risk():
    r = v()
    assert "no sponsorship stated and no permit record" in r.risks
    assert r.ireland["sponsorship_silent"] and r.ireland["permit_record"] is None


def test_record_mentions_count():
    r = v(record=(2026, 41))
    assert "has sponsored 41 permits in 2026" in permit(r).message
    assert not any("permit record" in x for x in r.risks)
    assert r.ireland["permit_record"] == [2026, 41]


def test_missing_dete_cache_text():
    r = v(dete_imported=False)
    assert "no sponsorship stated and no permit record (DETE data not imported)" in r.risks


def test_sponsorship_offered_no_record_risk():
    r = v(sponsorship="offered")
    assert not r.ireland["sponsorship_silent"]
    assert not any("permit record" in x for x in r.risks)


# Warnings


def test_ielts_is_warning_not_skip():
    r = v(english_test=("IELTS", "other"))
    assert r.passed
    assert ("asks for IELTS; you hold EF SET English Certificate, C1 Advanced (67/100) "
            "(not a substitute)") in r.warnings


def test_english_test_without_efset():
    m = copy.deepcopy(IE_MASTER)
    m["certificates"] = []
    assert "asks for TOEFL" in v(master=m, english_test=("TOEFL",)).warnings


def test_strict_degree_warning_uses_study_type():
    r = v(degree="required")
    assert "strict degree requirement; Associate Degree may not satisfy it" in r.warnings


def test_missing_soc_warns_and_needs_lmnt():
    r = v(soc=None, salary=50000)
    assert "no SOC code recorded; CSOL status unknown" in r.warnings
    assert r.ireland["route"] == "gep" and r.ireland["soc"] is None
    assert "GEP only; needs a labour market test" in r.risks


# Salary conversion


def test_gbp_hourly_converted():
    r = v(salary=40, currency="GBP", period="hour")
    expected = 40 * 168 * 12 / 0.85
    assert r.ireland["salary_eur_year"] == pytest.approx(expected)
    assert r.ireland["route"] == "csep"  # about 94,870 EUR/year


def test_min_only_salary_used():
    r = v(salary=None, lo=45000)
    assert r.ireland["salary_eur_year"] == 45000
    assert r.ireland["route"] == "csep-if-degree"


def test_salary_unknown_risk():
    r = v(salary=None)
    assert r.passed and r.ireland["route"] == "unknown"
    assert "salary unknown; CSEP needs 40,904 with a recognised degree or 68,911" in r.risks


def test_non_eur_without_rates_is_risk_not_crash():
    r = v(rates=None, salary=5000, currency="USD", period="month")
    assert r.passed and r.ireland["route"] == "unknown"
    assert "salary in USD could not be converted; not compared" in r.risks


def test_eur_year_needs_no_rates():
    assert v(rates=None, salary=55000).ireland["route"] == "csep-if-degree"


def test_ie_without_personal_floor_salary_rule_passes():
    r = v(salary=55000)
    salary = next(x for x in r.results if x.rule == "salary")
    assert salary.ok
    assert salary.message == ("no personal floor for Ireland; "
                              "permit floors checked by the permit rule")


def test_ie_floor_in_eur_year_compared_in_eur_year():
    m = copy.deepcopy(IE_MASTER)
    m["x-preferences"]["payFloor"] = {"IE": {"amount": 60000, "currency": "EUR",
                                             "period": "year"}}
    r = v(master=m, rates=None, salary=55000)
    salary = next(x for x in r.results if x.rule == "salary")
    assert not salary.ok and not r.passed
    assert "60,000 EUR/year" in salary.message


def test_irish_job_results_order():
    assert [x.rule for x in v().results] == ["years", "permit", "salary", "languages"]


def test_br_job_unchanged_for_ie_master():
    r_br = req(workplace="hybrid", countries=["Brazil"])
    base = check(r_br, posting(), MASTER, None, RATES, TODAY, clt_factor=1.4)
    ie = check(r_br, posting(), {**IE_MASTER, "x-preferences": {
        **IE_MASTER["x-preferences"], "payFloor": MASTER["x-preferences"]["payFloor"]}},
        None, RATES, TODAY, clt_factor=1.4, table=TABLE)
    assert base.results == ie.results and base.passed == ie.passed
    assert ie.ireland is None and ie.risks == []


# CLI


IE_DESCRIPTION = ("Senior Engineer. 5+ years of experience required.\n"
                  "Hybrid, Dublin. We pay 55000 EUR per year.")


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


def test_cli_check_writes_risks_and_ireland(env, capsys):
    r = ie_req()
    r["location"]["quote"] = "Hybrid, Dublin."
    r["salary"]["quote"] = "We pay 55000 EUR per year."
    app = env / "applications" / "acme-senior-engineer"
    posting(description=IE_DESCRIPTION).save(app)
    (app / "requirements.yaml").write_text(yaml.safe_dump(r), encoding="utf-8")
    tracker.upsert(env / "tracker.csv",
                   {"slug": "acme-senior-engineer", "company": "Acme", "role": "Senior Engineer",
                    "date": "2026-10-21", "status": "drafted"})
    data = yaml.safe_load(PERSONA.read_text(encoding="utf-8"))
    data["x-preferences"]["workRights"] = IE_MASTER["x-preferences"]["workRights"]
    master = env / "ie-master.yaml"
    master.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert cli.main(["check", "acme-senior-engineer", "--master", str(master)]) == 0
    out = capsys.readouterr().out
    assert "PASS permit: " in out
    assert "RISK CSEP only if the Tecnólogo is recognised" in out
    assert "RISK no sponsorship stated and no permit record (DETE data not imported)" in out
    verdict = json.loads((app / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "pass"
    assert verdict["ireland"]["route"] == "csep-if-degree"
    assert verdict["risks"][0].startswith("CSEP only if")

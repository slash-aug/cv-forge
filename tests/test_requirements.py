import pytest
import yaml

from cvforge.apply.requirements import (
    RequirementsError,
    load_requirements,
    normalise_quote,
    quote_problems,
)

POSTING = (
    "We’re hiring a Frontend Engineer.\n"
    "You have 3–5 years of experience with React.\n"
    "Location: Remote,   worldwide.\n"
    "Salary: 4000 USD per month."
)


def _req(**over):
    req = {
        "years": [{"min": 3, "kind": "required", "quote": "3-5 years of experience with React"}],
        "location": {"workplace": "remote", "job_countries": [], "allowed": ["worldwide"],
                     "quote": "Remote, worldwide."},
        "sponsorship": {"status": "silent", "quote": None},
        "salary": {"min": None, "max": None, "currency": None, "period": None, "quote": None},
        "languages_required": [],
    }
    req.update(over)
    return req


def _write(tmp_path, data):
    path = tmp_path / "requirements.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_valid(tmp_path):
    req = load_requirements(_write(tmp_path, _req()))
    assert req["location"]["allowed"] == ["worldwide"]
    assert req["salary"]["contract"] == "unknown"


def test_load_rejects_bad_workplace(tmp_path):
    bad = _req(location={"workplace": "office", "job_countries": [], "allowed": [], "quote": None})
    with pytest.raises(RequirementsError, match="location.workplace"):
        load_requirements(_write(tmp_path, bad))


def test_load_needs_quote_for_offered_sponsorship(tmp_path):
    with pytest.raises(RequirementsError, match="sponsorship.quote"):
        load_requirements(_write(tmp_path, _req(sponsorship={"status": "offered", "quote": None})))


def test_load_needs_currency_for_salary(tmp_path):
    salary = {"min": None, "max": 5000, "currency": None, "period": "month", "quote": "5000"}
    with pytest.raises(RequirementsError, match="salary.currency"):
        load_requirements(_write(tmp_path, _req(salary=salary)))


def test_load_accepts_contract_and_language_without_level(tmp_path):
    salary = {"min": 8000, "max": 10000, "currency": "BRL", "period": "month",
              "contract": "clt", "quote": "R$ 8.000 a R$ 10.000 CLT"}
    langs = [{"lang": "en", "quote": "English"}]
    req = load_requirements(_write(tmp_path, _req(salary=salary, languages_required=langs)))
    assert req["salary"]["contract"] == "clt"


def test_normalise_quote():
    assert normalise_quote("We’re “here” – now  \n ok") == "we're \"here\" - now ok"


def test_quote_typography_tolerated():
    req = _req(years=[{"min": 3, "kind": "required", "quote": "we're HIRING"}],
               location={"workplace": "remote", "job_countries": [], "allowed": ["worldwide"],
                         "quote": "Location: Remote, worldwide."})
    req["years"].append({"min": 5, "kind": "preferred", "quote": "3–5 years of experience"})
    assert quote_problems(req, POSTING) == []


def test_changed_word_fails():
    req = _req(years=[{"min": 3, "kind": "required", "quote": "3-5 years of experience with Vue"}])
    problems = quote_problems(req, POSTING)
    assert len(problems) == 1
    assert problems[0].startswith("years.0.quote")


def test_quote_problems_cover_every_field():
    req = _req(
        sponsorship={"status": "offered", "quote": "we sponsor visas"},
        salary={"min": None, "max": 4000, "currency": "USD", "period": "month",
                "quote": "Salary: 5000 USD"},
        languages_required=[{"lang": "de", "level": "B2", "quote": "German B2"}],
    )
    problems = quote_problems(req, POSTING)
    assert [p.split(":")[0] for p in problems] == [
        "sponsorship.quote", "salary.quote", "languages_required.0.quote"]

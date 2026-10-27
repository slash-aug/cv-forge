import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.answers.bank import load_bank, lookup, normalise_question, save_answers
from cvforge.answers.facts import knockout_facts
from cvforge.answers.gupy import GUPY_QUESTIONS
from cvforge.apply.experience import engineering_months
from cvforge.apply.posting import Posting
from cvforge.profile.model import load_master

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
MASTER = load_master(PERSONA / "master.yaml")
TODAY = date(2026, 10, 22)


def test_normalise_question_ignores_punctuation_and_case():
    a = normalise_question("Are you   legally authorised to work in the EU?")
    b = normalise_question("are you legally authorised to work in EU")
    assert a == b and a
    assert normalise_question("Você tem visto?") == normalise_question("voce tem visto")


def test_lookup_respects_lang(tmp_path):
    path = tmp_path / "bank.yaml"
    save_answers(path, [{"question": "Why us?", "answer": "Because.", "refs": []}],
                 "en", TODAY)
    bank = load_bank(path)
    assert lookup(bank, "why us", "en")["answer"] == "Because."
    assert lookup(bank, "why us", "pt-BR") is None
    assert lookup(bank, "something else", "en") is None


def test_save_updates_last_used_and_dedupes(tmp_path):
    path = tmp_path / "bank.yaml"
    assert save_answers(path, [{"question": "Why us?", "answer": "A", "refs": ["x"]}],
                        "en", date(2026, 1, 1)) == 1
    save_answers(path, [{"question": "why us", "answer": "B", "refs": []}],
                 "en", TODAY)
    save_answers(path, [{"question": "why us", "answer": "C", "refs": []}],
                 "pt-BR", TODAY)
    bank = load_bank(path)
    assert len(bank) == 2
    en = lookup(bank, "Why us?", "en")
    assert (en["answer"], en["last_used"]) == ("B", "2026-10-22")
    assert set(en) == {"key", "question", "answer", "refs", "lang", "last_used"}
    assert "\u2014" not in path.read_text(encoding="utf-8")


def test_knockout_years_text_en_pt():
    f = lambda m, lang: knockout_facts(MASTER, m, lang)["years"]
    assert f(17, "en") == "1 year 5 months"
    assert f(17, "pt-BR") == "1 ano e 5 meses"
    assert f(17, "pt-PT") == "1 ano e 5 meses"
    assert f(24, "en") == "2 years"
    assert f(36, "pt-PT") == "3 anos"
    assert f(13, "en") == "1 year 1 month"
    assert f(13, "pt-BR") == "1 ano e 1 mês"
    assert f(1, "en") == "1 month"
    assert f(5, "pt-BR") == "5 meses"
    assert f(0, "en") == "0 months"


def test_knockout_other_facts():
    f = knockout_facts(MASTER, 30, "pt-BR")
    assert f["visa"] == "EU: not needed"
    assert f["relocation"] == "não"
    assert f["notice"] == "30 days"
    assert f["location"] == "Lisbon, PT"
    assert f["languages"] == "Português: Nativo; English: Fluente"
    en = knockout_facts(MASTER, 30, "en")
    assert en["relocation"] == "no"
    assert en["languages"] == "Portuguese: Native; English: Fluent"


# CLI


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    d = tmp_path / "applications" / "acme"
    d.mkdir(parents=True)
    return d


def _tailored(d, mutate=None):
    t = yaml.safe_load((PERSONA / "tailored.yaml").read_text(encoding="utf-8"))
    t["answers"] = [{"question": "Why us?", "answer": "I like the product.", "refs": [],
                     "limit": None}]
    if mutate:
        mutate(t)
    (d / "tailored.yaml").write_text(yaml.safe_dump(t, allow_unicode=True), encoding="utf-8")


def _run(*extra):
    return cli.main(["answers", "acme", "--master", str(PERSONA / "master.yaml"), *extra])


def test_save_then_lookup_via_cli(app, tmp_path, capsys):
    _tailored(app)
    assert _run("--save") == 0
    bank = tmp_path / "answers" / "bank.yaml"
    assert load_bank(bank)[0]["answer"] == "I like the product."
    (app / "questions.txt").write_text("Why us?\nSalary expectations?\n", encoding="utf-8")
    capsys.readouterr()
    assert _run() == 0
    out = capsys.readouterr().out
    assert "I like the product." in out and "NEW" in out and "notice" in out


def test_save_refuses_when_audit_fails(app, tmp_path, capsys):
    _tailored(app, lambda t: t["answers"][0].update(answer="Bad \u2014 dash"))
    assert _run("--save") == 1
    assert not (tmp_path / "answers" / "bank.yaml").exists()
    assert capsys.readouterr().err.strip()


def test_unknown_slug(app):
    assert cli.main(["answers", "nope"]) == 1


def _posting(d, source):
    Posting(company="Acme", title="Dev", location="", location_requirements=[], workplace=None,
            salary=None, language="pt", url="https://acme.example/jobs/1", apply_url=None,
            source=source, fetched="2026-10-27", description="").save(d)


def test_gupy_posting_adds_the_standard_questions(app, capsys):
    _posting(app, "gupy")
    assert _run() == 0
    out = capsys.readouterr().out
    for question in GUPY_QUESTIONS:
        assert f"Q: {question['question']}" in out
    assert "limit 1500" in out


def test_gupy_questions_are_not_repeated_from_questions_txt(app, capsys):
    _posting(app, "gupy")
    (app / "questions.txt").write_text(GUPY_QUESTIONS[0]["question"] + "\nWhy us?\n", encoding="utf-8")
    assert _run() == 0
    out = capsys.readouterr().out
    assert out.count(f"Q: {GUPY_QUESTIONS[0]['question']}") == 1
    assert "Q: Why us?" in out


def test_gupy_skills_print_from_data(app, tmp_path, capsys):
    _posting(app, "gupy")
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / "gupy.yaml").write_text("skills: [Python, SQL]\n", encoding="utf-8")
    assert _run() == 0
    assert "Gupy skills: Python, SQL" in capsys.readouterr().out


def test_other_sources_get_no_gupy_questions(app, capsys):
    _posting(app, "greenhouse")
    assert _run() == 0
    assert GUPY_QUESTIONS[0]["question"] not in capsys.readouterr().out




# Knock-out and salary figures in answers (computed, so not in any highlight)


def _answers(d, *texts):
    _tailored(d, lambda t: t.update(answers=[
        {"question": f"Q{i}", "answer": a, "refs": [], "limit": None}
        for i, a in enumerate(texts)]))


def _audit(d):
    return cli.main(["audit", str(d / "tailored.yaml"), "--master", str(PERSONA / "master.yaml")])


def _salary_json(d, confirmed):
    data = {"basis": "posting", "amount": 3500.0, "currency": "EUR", "period": "month",
            "brl_month": 21012.34, "eur_year": 42000.0, "usd_year": 46199.6, "sources": [],
            "confirmed": confirmed, "rates_day": "2026-10-21"}
    (d / "salary.json").write_text(json.dumps(data), encoding="utf-8")


def test_knockout_answers_audit_clean(app, capsys):
    years = knockout_facts(MASTER, engineering_months(MASTER, TODAY), "en")["years"]
    _answers(app, f"I have {years} of engineering experience.", "My notice period is 30 days.")
    assert _audit(app) == 0, capsys.readouterr().out
    assert _run("--save") == 0


def test_confirmed_salary_answer_audits_clean(app, capsys):
    _answers(app, "My expectation is 3,500 EUR per month (about R$ 21.012 or 42,000 EUR a year).")
    _salary_json(app, confirmed=True)
    assert _audit(app) == 0, capsys.readouterr().out


def test_unconfirmed_salary_and_invented_numbers_fail(app, capsys):
    _answers(app, "My expectation is 3,500 EUR per month.")
    _salary_json(app, confirmed=False)
    assert _audit(app) == 1
    _answers(app, "I have 12 years of engineering experience.")
    _salary_json(app, confirmed=True)
    assert _audit(app) == 1
    assert "not in the master text: 12" in capsys.readouterr().out
    assert _run("--save") == 1


@pytest.mark.parametrize("asked,other", [
    ("Do you need sponsorship?", "Do you have sponsorship?"),
    ("Você precisa de visto?", "Você tem visto?"),
])
def test_need_and_have_questions_stay_distinct(tmp_path, asked, other):
    assert normalise_question(asked) != normalise_question(other)
    path = tmp_path / "bank.yaml"
    save_answers(path, [{"question": asked, "answer": "Yes.", "refs": []}], "en", TODAY)
    save_answers(path, [{"question": other, "answer": "No.", "refs": []}], "en", TODAY)
    bank = load_bank(path)
    assert len(bank) == 2
    assert lookup(bank, asked, "en")["answer"] == "Yes."
    assert lookup(bank, other, "en")["answer"] == "No."


def test_visa_keys_read_as_names():
    from cvforge.answers.facts import visa_text

    assert visa_text({"eu_blue_card": "eligible", "portugal": "CPLP mobility"}) == (
        "EU Blue Card: eligible; Portugal: CPLP mobility")
    assert visa_text({"EU": "not needed", "uk_skilled_worker": "no"}) == "EU: not needed; UK Skilled Worker: no"
    assert visa_text({}) == "" and visa_text(None) == ""
    assert visa_text("Needs sponsorship") == "Needs sponsorship"


def test_knockout_visa_uses_names():
    master = {**MASTER, "x-preferences": {**MASTER["x-preferences"],
                                          "visa": {"eu_blue_card": "eligible"}}}
    assert knockout_facts(master, 24, "en")["visa"] == "EU Blue Card: eligible"


def test_normalise_matches_shared_table():
    rows = json.loads((Path(__file__).parent / "fixtures" / "normalise_table.json").read_text("utf-8"))
    assert len(rows) >= 15
    for row in rows:
        assert normalise_question(row["question"]) == row["key"], row["question"]

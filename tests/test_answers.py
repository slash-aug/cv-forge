from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.answers.bank import load_bank, lookup, normalise_question, save_answers
from cvforge.answers.facts import knockout_facts
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



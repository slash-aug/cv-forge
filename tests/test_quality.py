import copy
from pathlib import Path

from cvforge.checks.quality import cv_warnings, kit_warnings
from cvforge.profile.model import load_master
from cvforge.tailor.audit import load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
MASTER = load_master(PERSONA / "master.yaml")
LEAD = "p-examplepay-lead"


def _master(form=None, labels=None):
    master = copy.deepcopy(MASTER)
    for employer in master["work"]:
        for position in employer["positions"]:
            position.pop("x-form", None)
    if form:
        master["work"][0]["positions"][0]["x-form"] = form
    if labels:
        master["skills"][2]["x-labels"] = labels
    return master


def _tailored(refs, lang="en", skills=()):
    base = load_tailored(PERSONA / "tailored.yaml")
    return {**base, "lang": lang, "skills": list(skills), "experience": [
        {"ref": "w-examplepay", "positions": [
            {"ref": LEAD, "bullets": [{"ref": r, "text": f"Did {r}."} for r in refs]}]}]}


FORM = {"context": {"en": "Payments team at a made-up company."},
        "pinned": [{"ref": "h-mentoring"}], "cv_lead": True}


def _has(warnings, *words):
    return any(all(w in warning for w in words) for warning in warnings)


def test_more_than_six_bullets():
    assert _has(cv_warnings(_tailored(["h-team-lead"] * 7), _master()), LEAD, "7 bullets")
    assert not _has(cv_warnings(_tailored(["h-team-lead"] * 6), _master()), "bullets")


def test_cv_lead_not_first_or_absent():
    for refs in (["h-team-lead", "h-mentoring"], ["h-team-lead"]):
        assert _has(cv_warnings(_tailored(refs), _master(FORM)), LEAD, "h-mentoring")
    assert cv_warnings(_tailored(["h-mentoring", "h-team-lead"]), _master(FORM)) == []


def test_missing_skill_label_on_portuguese_cv():
    skills = [{"ref": "sk-practices", "keywords": ["Testing"]}]
    master = _master(labels={"Testing": {"pt-PT": "Testes"}})
    assert _has(cv_warnings(_tailored([], "pt-BR", skills), master), "Testing", "pt-BR")
    assert not _has(cv_warnings(_tailored([], "pt-PT", skills), master), "Testing")
    assert not _has(cv_warnings(_tailored([], "en", skills), master), "Testing")


def test_position_without_form():
    assert _has(kit_warnings(_tailored(["h-team-lead", "h-mentoring"]), _master()), LEAD, "x-form")


def test_missing_translations():
    tailored = _tailored(["h-team-lead", "h-mentoring"], "pt-BR")
    assert _has(kit_warnings(tailored, _master(FORM)), LEAD, "context", "pt-BR")
    form = {"context": {"pt-BR": "Time de pagamentos."},
            "pinned": [{"ref": "h-payments-integration", "short": {"en": "Payments."}}]}
    assert _has(kit_warnings(tailored, _master(form)), "h-payments-integration", "short", "pt-BR")
    master = _master({**form, "pinned": [{"ref": "h-mentoring"}]})
    master["work"][0]["positions"][0]["highlights"][2]["impact"] = {"en": "Mentored."}
    assert _has(kit_warnings(_tailored([], "pt-BR"), master), "h-mentoring", "no text", "pt-BR")


def test_short_variant_without_first_pinned():
    form = {"context": {"en": "c" * 190}, "pinned": [{"ref": "h-mentoring"}]}
    assert _has(kit_warnings(_tailored(["h-team-lead"]), _master(form)), LEAD, "200")


def test_one_line_description():
    assert _has(kit_warnings(_tailored(["h-team-lead"]), _master()), LEAD, "one line")
    assert _has(kit_warnings(_tailored([]), _master()), LEAD, "empty")
    assert kit_warnings(_tailored(["h-team-lead"]), _master(FORM)) == []

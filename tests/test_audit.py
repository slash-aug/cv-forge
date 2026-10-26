import copy
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, index, load_master
from cvforge.tailor.audit import EM_DASH, Finding, audit, audit_answer, load_tailored

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
M = load_master(PERSONA / "master.yaml")
T = load_tailored(PERSONA / "tailored.yaml")


def _variant(mutate):
    data = copy.deepcopy(T)
    mutate(data)
    return data


def _bullet(data, ref):
    for work in data["experience"]:
        for position in work["positions"]:
            for bullet in position["bullets"]:
                if bullet["ref"] == ref:
                    return bullet
    raise KeyError(ref)


def _kinds(data):
    return [f.kind for f in audit(data, M)]


def test_example_is_grounded():
    assert audit(T, M) == []


def test_escalated_metric_flagged():
    t = _variant(lambda d: _bullet(d, "h-load-time").update(text="Cut load time by 45% at the edge."))
    assert [f.kind for f in audit(t, M)] == ["number"]
    assert audit(t, M)[0].ref == "h-load-time"


def test_number_matches_any_locale():
    t = _variant(lambda d: _bullet(d, "h-onboarding").update(text="Doubling 2 activation."))
    assert _kinds(t) == ["number"]


def test_summary_numbers_checked_against_highlights():
    ok = _variant(lambda d: d["summary"].update(text="Cut load time by 40% and led 5 engineers."))
    bad = _variant(lambda d: d["summary"].update(text="Cut load time by 41%."))
    assert _kinds(ok) == []
    assert _kinds(bad) == ["number"]


def test_unknown_ref():
    t = _variant(lambda d: _bullet(d, "h-load-time").update(ref="nope"))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("unknown-ref", "nope")]


def test_wrong_kind_ref_is_unknown_ref():
    t = _variant(lambda d: d.update(education=["cert-cloud"]))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("unknown-ref", "cert-cloud")]


def test_unknown_work_and_position_each_one_finding():
    def bad(d):
        d["experience"][0]["ref"] = "w-nope"
        d["experience"][0]["positions"][0]["ref"] = "p-nope"

    assert [f.ref for f in audit(_variant(bad), M)] == ["w-nope", "p-nope"]


def test_highlight_under_wrong_position():
    t = _variant(lambda d: _bullet(d, "h-team-lead").update(ref="h-load-time"))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [
        ("wrong-parent", "h-load-time"),
        ("number", "h-load-time"),
    ]


def test_position_under_wrong_work():
    t = _variant(lambda d: d["experience"][0]["positions"][0].update(ref="p-examplepay-dev"))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [
        ("wrong-parent", "p-examplepay-dev"),
        ("wrong-parent", "h-onboarding"),
    ]


def test_confidential_case_insensitive():
    t = _variant(lambda d: d["letter"]["paragraphs"].append("I worked on ProjectZebra."))
    found = [f for f in audit(t, M) if f.kind == "confidential"]
    assert len(found) == 1 and found[0].ref == "letter.paragraphs.2"


def test_confidential_in_target_and_summary():
    def leak(d):
        d["target"]["company"] = "PROJECTZEBRA Inc"
        d["summary"]["text"] = "projectzebra veteran."

    refs = [f.ref for f in audit(_variant(leak), M) if f.kind == "confidential"]
    assert refs == ["target.company", "summary"]


def test_keyword_not_in_master():
    t = _variant(lambda d: d["skills"][0]["keywords"].append("Cobol"))
    assert audit(t, M) == [Finding("skill-keyword", "sk-backend", "'Cobol' is not a keyword of this skill")]


def test_findings_in_document_order():
    def many(d):
        d["skills"][0]["keywords"].append("Cobol")
        _bullet(d, "h-load-time").update(text="Cut 99%.")
        d["education"] = ["nope"]

    assert _kinds(_variant(many)) == ["number", "skill-keyword", "unknown-ref"]


def test_load_tailored_rejects_bad_schema(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text("lang: fr\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="lang"):
        load_tailored(path)


def test_letter_escalated_number_flagged():
    t = _variant(lambda d: d["letter"]["paragraphs"].__setitem__(1, "I cut load time by 90%."))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("number", "letter.paragraphs.1")]


def test_letter_opening_and_closing_numbers_flagged():
    def bump(d):
        d["letter"]["opening"] = "Dear team, 7 reasons."
        d["letter"]["closing"] = "Regards, 9."

    refs = [(f.kind, f.ref) for f in audit(_variant(bump), M)]
    assert refs == [("number", "letter.opening"), ("number", "letter.closing")]


def test_letter_numbers_grounded_by_any_highlight():
    t = _variant(lambda d: d["letter"]["paragraphs"].append("I mentored 3 engineers."))
    assert audit(t, M) == []


@pytest.mark.parametrize("variant", ["Project Zebra", "project-zebra", "PROJECT_ZEBRA", "ＰｒｏｊｅｃｔＺｅｂｒａ"])
def test_confidential_separator_and_width_variants(variant):
    t = _variant(lambda d: d["letter"]["paragraphs"].append(f"Worked on {variant} once."))
    assert [f.kind for f in audit(t, M)] == ["confidential"]


def test_confidential_in_bullet_and_keyword():
    def leak(d):
        _bullet(d, "h-load-time").update(text="Cut load time by 40% on ProjectZebra.")
        d["skills"][0]["keywords"].append("projectzebra")

    got = [(f.kind, f.ref) for f in audit(_variant(leak), M)]
    assert ("confidential", "h-load-time") in got
    assert ("confidential", "sk-backend") in got


def test_decimal_comma_grounded_by_decimal_point():
    m = copy.deepcopy(M)
    for _, item in index(m).values():
        if item.get("id") == "h-load-time":
            item["impact"] = "Cut load time by 40% to 2.5 seconds."
    t = _variant(lambda d: _bullet(d, "h-load-time").update(text="Cut load time to 2,5 seconds."))
    assert audit(t, m) == []


def test_rendered_values_scanned_with_field_path():
    from cvforge.tailor.audit import audit_rendered

    rendered = {"experience": [{"employer": "Acme"}, {"employer": "Project Zebra Labs"}],
                "contact": {"links": [{"text": "x", "href": "https://projectzebra.example"}]}}
    found = audit_rendered(M, cv=rendered)
    assert [(f.kind, f.ref) for f in found] == [
        ("confidential", "cv.experience.1.employer"),
        ("confidential", "cv.contact.links.0.href"),
    ]


def test_rendered_values_clean():
    from cvforge.tailor.audit import audit_rendered

    assert audit_rendered(M, cv={"a": ["plain", {"b": "text"}]}, letter={"name": "Ana"}) == []


def test_pt_br_persona_is_grounded():
    assert audit(load_tailored(PERSONA / "tailored.pt-BR.yaml"), M) == []


EM = chr(0x2014)


def _para(d, i, text, refs):
    d["letter"]["paragraphs"][i] = {"text": text, "refs": refs}


def test_letter_paragraph_refs_limit_numbers():
    ok = _variant(lambda d: _para(d, 1, "I cut load time by 40%.", ["h-load-time"]))
    bad = _variant(lambda d: _para(d, 1, "I led 5 engineers.", ["h-load-time"]))
    assert audit(ok, M) == []
    assert [(f.kind, f.ref) for f in audit(bad, M)] == [("number", "letter.paragraphs.1")]


def test_letter_unknown_ref():
    t = _variant(lambda d: _para(d, 1, "Plain text.", ["h-nope"]))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("unknown-ref", "h-nope")]


def test_string_paragraph_still_broad():
    t = _variant(lambda d: d["letter"]["paragraphs"].append("I led 5 engineers and cut 40%."))
    assert audit(t, M) == []


def test_recruiter_connect_over_160():
    t = _variant(lambda d: d.update(recruiter_note={"connect": "x" * 161, "message": "Hi.", "refs": []}))
    found = audit(t, M)
    assert [(f.kind, f.ref) for f in found] == [("length", "recruiter_note.connect")]
    assert "160" in found[0].message and "200" in found[0].message
    t = _variant(lambda d: d.update(recruiter_note={"connect": "x" * 160, "message": "m" * 1201, "refs": []}))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("length", "recruiter_note.message")]


def test_recruiter_note_numbers_follow_refs():
    note = {"connect": "Hi.", "message": "I cut load time by 40%.", "refs": ["h-load-time"]}
    assert audit(_variant(lambda d: d.update(recruiter_note=note)), M) == []
    bad = {**note, "message": "I led 5 engineers.", "refs": ["h-load-time"]}
    assert [f.kind for f in audit(_variant(lambda d: d.update(recruiter_note=bad)), M)] == ["number"]


def test_answer_over_limit():
    ans = [{"question": "Why?", "answer": "a" * 11, "refs": [], "limit": 10}]
    t = _variant(lambda d: d.update(answers=ans))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("length", "answers.0.answer")]
    ans[0]["limit"] = None
    assert audit(_variant(lambda d: d.update(answers=ans)), M) == []


def test_em_dash_anywhere():
    t = _variant(lambda d: d["summary"].update(text=f"Engineer {EM} builder."))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("em-dash", "summary")]
    t = _variant(lambda d: d.update(answers=[{"question": "q", "answer": f"a{EM}b", "refs": [], "limit": None}]))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("em-dash", "answers.0.answer")]


def test_confidential_in_answer():
    ans = [{"question": "q", "answer": "I did ProjectZebra.", "refs": [], "limit": None}]
    t = _variant(lambda d: d.update(answers=ans))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("confidential", "answers.0.answer")]


def test_persona_tailored_still_clean():
    assert "recruiter_note" in T
    assert any(isinstance(p, dict) for p in T["letter"]["paragraphs"])
    assert audit(T, M) == []


def _answer(text):
    return _variant(lambda d: d.update(answers=[
        {"question": "How many years?", "answer": text, "refs": [], "limit": None}]))


def test_extra_allowed_numbers_apply_to_answers():
    t = _answer("I have 6 years and 9 months of experience.")
    assert _kinds(t) == ["number"]
    assert audit(t, M, extra_allowed={"6", "9"}) == []
    assert [f.message for f in audit(t, M, extra_allowed={"6"})] == ["not in the master text: 9"]


def test_extra_allowed_numbers_do_not_apply_to_letter():
    t = _variant(lambda d: d["letter"].update(closing="Available in 30 days."))
    assert [f.ref for f in audit(t, M, extra_allowed={"30"})] == ["letter.closing"]


EMAIL = {"to": "jobs@example.com", "subject": "Full-stack role: Ana Exemplo",
         "body": "Hi team,\n\nI cut load time by 40%.\n\nThank you.", "refs": ["h-load-time"]}


def test_email_numbers_follow_refs():
    assert audit(_variant(lambda d: d.update(email=EMAIL)), M) == []
    bad = {**EMAIL, "body": "Hi team,\n\nI led 5 engineers."}
    found = audit(_variant(lambda d: d.update(email=bad)), M)
    assert [(f.kind, f.ref) for f in found] == [("number", "email.body")]


def test_email_em_dash_and_confidential():
    t = _variant(lambda d: d.update(email={**EMAIL, "subject": f"Role {EM} Ana"}))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("em-dash", "email.subject")]
    t = _variant(lambda d: d.update(email={**EMAIL, "body": "I did ProjectZebra."}))
    assert [(f.kind, f.ref) for f in audit(t, M)] == [("confidential", "email.body")]


def test_email_schema_requires_every_part():
    from cvforge.profile.model import load_schema, schema_problems

    schema = load_schema("cvforge.tailor", "tailored.schema.json")
    assert schema_problems(_variant(lambda d: d.update(email=EMAIL)), schema) == []
    for key in ("to", "subject", "body", "refs"):
        partial = {k: v for k, v in EMAIL.items() if k != key}
        assert schema_problems(_variant(lambda d, p=partial: d.update(email=p)), schema), key


def test_audit_answer_grounded_number_passes():
    assert audit_answer("Impact?", "I cut load time by 40%.", M) == []


def test_audit_answer_invented_number_fails():
    f = audit_answer("Impact?", "I cut load time by 45%.", M)
    assert [x.kind for x in f] == ["number"] and "45" in f[0].message
    assert f[0].ref == "answer"


def test_audit_answer_extra_allowed():
    assert audit_answer("Salary?", "60000 EUR", M, extra_allowed={"60000"}) == []


def test_audit_answer_confidential_em_dash_and_limit():
    f = audit_answer("About projectzebra?", f"Worked on projectzebra {EM_DASH} a lot.", M, limit=10)
    assert [(x.kind, x.ref) for x in f] == [
        ("em-dash", "answer"),
        ("confidential", "question"),
        ("confidential", "answer"),
        ("length", "answer"),
    ]

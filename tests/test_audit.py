import copy
from pathlib import Path

import pytest

from cvforge.profile.model import ProfileError, load_master
from cvforge.tailor.audit import Finding, audit, load_tailored

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

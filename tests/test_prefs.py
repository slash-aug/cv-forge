from pathlib import Path

import pytest
import yaml

from cvforge.profile.model import ProfileError, load_master
from cvforge.profile.prefs import (
    degree_recognised,
    home_codes,
    pay_floor,
    primary_market,
    self_apply,
)

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona" / "master.yaml"
FLOOR = {"amount": 3000, "currency": "BRL", "period": "month"}


def _variant(tmp_path, prefs_update):
    data = yaml.safe_load(PERSONA.read_text(encoding="utf-8"))
    data["x-preferences"].update(prefs_update)
    path = tmp_path / "master.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_persona_without_work_rights_keeps_br_pt_home():
    assert home_codes(load_master(PERSONA)) == {"BR", "PT"}


def test_home_from_work_rights():
    m = {"x-preferences": {"workRights": {"BR": {"status": "citizen"},
         "PT": {"status": "mobility"}, "IE": {"status": "needs-permit"}}}}
    assert home_codes(m) == {"BR", "PT"}


def test_single_pay_floor_applies_everywhere():
    m = {"x-preferences": {"payFloor": FLOOR}}
    assert pay_floor(m, "IE") == pay_floor(m, "BR") == FLOOR


def test_pay_floor_map_by_market():
    m = {"x-preferences": {"payFloor": {"BR": FLOOR}}}
    assert pay_floor(m, "IE") is None and pay_floor(m, "BR")["currency"] == "BRL"


def test_pay_floor_map_default():
    m = {"x-preferences": {"payFloor": {"default": FLOOR}}}
    assert pay_floor(m, "IE") == FLOOR


def test_schema_accepts_work_rights_and_floor_map(tmp_path):
    path = _variant(tmp_path, {
        "workRights": {"IE": {"status": "needs-permit", "degreeRecognised": "yes",
                              "soc": ["2134"], "selfApply": True}},
        "payFloor": {"BR": FLOOR, "default": {**FLOOR, "currency": "EUR"}},
    })
    master = load_master(path)
    assert degree_recognised(master) == "yes" and self_apply(master) is True


def test_schema_rejects_unknown_status(tmp_path):
    path = _variant(tmp_path, {"workRights": {"IE": {"status": "maybe"}}})
    with pytest.raises(ProfileError):
        load_master(path)


def test_primary_market_and_degree_default():
    m = {"x-preferences": {"markets": ["ie", "BR"], "workRights": {"IE": {"status": "needs-permit"}}}}
    assert primary_market(m) == "IE" and degree_recognised(m) == "unknown" and self_apply(m) is False


def test_empty_work_rights_keeps_default_home():
    assert home_codes({"x-preferences": {"workRights": {}}}) == {"BR", "PT"}


def test_ireland_pay_floor_only_explicit_ie_entry():
    from cvforge.profile.prefs import ireland_pay_floor

    ie = {"amount": 60000, "currency": "EUR", "period": "year"}
    assert ireland_pay_floor({"x-preferences": {"payFloor": FLOOR}}) is None
    assert ireland_pay_floor({"x-preferences": {"payFloor": {"default": FLOOR}}}) is None
    assert ireland_pay_floor({"x-preferences": {"payFloor": {"IE": ie, "default": FLOOR}}}) == ie
    assert ireland_pay_floor({"x-preferences": {}}) is None

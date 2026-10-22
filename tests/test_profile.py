from pathlib import Path

import pytest
import yaml

from cvforge.profile.model import ProfileError, index, load_master, localized

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona" / "master.yaml"


def _write_variant(tmp_path, mutate):
    data = yaml.safe_load(PERSONA.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "master.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_persona_valid():
    assert load_master(PERSONA)["basics"]["name"] == "Ana Exemplo"


def test_persona_has_expected_shape():
    master = load_master(PERSONA)
    assert len(master["x-summaries"]) == 2
    assert [w.get("x-international") for w in master["work"]] == [None, True, None]
    assert master["work"][1]["positions"][0]["endDate"] is None
    assert master["x-confidential"] == ["projectzebra"]


def test_duplicate_ids_rejected(tmp_path):
    def duplicate(data):
        data["work"][0]["positions"][0]["highlights"][1]["id"] = "h-payments-integration"

    with pytest.raises(ProfileError, match="h-payments-integration"):
        load_master(_write_variant(tmp_path, duplicate))


def test_schema_error_lists_path(tmp_path):
    with pytest.raises(ProfileError, match="basics"):
        load_master(_write_variant(tmp_path, lambda d: d["basics"].pop("email")))


def test_all_problems_listed(tmp_path):
    def break_two(data):
        data["basics"].pop("email")
        data["skills"][0]["keywords"] = "not-a-list"

    with pytest.raises(ProfileError) as err:
        load_master(_write_variant(tmp_path, break_two))
    assert "basics" in str(err.value) and "skills" in str(err.value)


def test_unknown_angle_rejected(tmp_path):
    def bad_angle(data):
        data["x-summaries"][0]["angles"] = ["nonsense"]

    with pytest.raises(ProfileError, match="x-summaries"):
        load_master(_write_variant(tmp_path, bad_angle))


def test_unknown_locale_key_rejected(tmp_path):
    def bad_locale(data):
        data["basics"]["label"] = {"fr": "x"}

    with pytest.raises(ProfileError, match="basics"):
        load_master(_write_variant(tmp_path, bad_locale))


def test_localized_plain_string_returned_as_is():
    assert localized("x", "pt-PT", item_id="h1") == "x"


def test_localized_picks_language():
    assert localized({"en": "a", "pt-BR": "b"}, "pt-BR", item_id="h1") == "b"


def test_localized_missing_lang():
    with pytest.raises(ProfileError, match="h1: missing translation 'pt-PT'"):
        localized({"en": "x"}, "pt-PT", item_id="h1")


def test_index_kinds():
    idx = index(load_master(PERSONA))
    assert idx["h-load-time"][0] == "highlight"
    assert idx["h-load-time"][1]["impact"].startswith("Cut load time by 40%")
    kinds = {kind for kind, _ in idx.values()}
    assert kinds == {
        "summary", "work", "position", "highlight",
        "skill", "education", "certificate", "language",
    }


def test_accented_text_survives_loading():
    idx = index(load_master(PERSONA))
    assert idx["h-payments-integration"][1]["impact"]["pt-BR"] == "Integração de pagamentos & reconciliação"


def test_persona_has_no_em_dash():
    assert "\u2014" not in PERSONA.read_text(encoding="utf-8")


def test_missing_file_raises_profile_error(tmp_path):
    with pytest.raises(ProfileError, match="nope.yaml"):
        load_master(tmp_path / "nope.yaml")


def test_malformed_yaml_raises_profile_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("basics: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="bad.yaml"):
        load_master(bad)


@pytest.mark.parametrize("content", ["", "- a\n- b\n", "just text\n"])
def test_empty_or_non_mapping_root_raises_profile_error(tmp_path, content):
    path = tmp_path / "m.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProfileError, match="m.yaml"):
        load_master(path)


def test_typo_locale_key_message(tmp_path):
    def typo(data):
        data["basics"]["label"] = {"en": "x", "pt_BR": "y"}

    with pytest.raises(ProfileError) as err:
        load_master(_write_variant(tmp_path, typo))
    assert "unexpected key 'pt_BR'; allowed: en, pt-BR, pt-PT" in str(err.value)
    assert "not valid under any" not in str(err.value)


def test_unquoted_end_date_message(tmp_path):
    def unquoted(data):
        data["work"][0]["positions"][0]["endDate"] = 2024

    with pytest.raises(ProfileError) as err:
        load_master(_write_variant(tmp_path, unquoted))
    text = str(err.value)
    assert "endDate" in text
    assert 'use a quoted "YYYY-MM" string or null' in text
    assert "not valid under any" not in text


def test_unquoted_education_year_message(tmp_path):
    def unquoted(data):
        data["education"][0]["endDate"] = 2019

    with pytest.raises(ProfileError, match='quoted "YYYY" or "YYYY-MM"'):
        load_master(_write_variant(tmp_path, unquoted))


def test_id_with_trailing_newline_rejected(tmp_path):
    def newline_id(data):
        data["skills"][0]["id"] = "sk-backend\n"

    with pytest.raises(ProfileError, match="skills.0.id"):
        load_master(_write_variant(tmp_path, newline_id))

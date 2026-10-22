from datetime import date

import pytest
import yaml

from cvforge.apply.companies import (
    CompanyError,
    add_company,
    add_sponsor,
    find_company,
    has_sponsor_mark,
    load_registry,
)
from cvforge.cli import main


def test_find_ignores_legal_suffix_and_case(tmp_path):
    path = tmp_path / "companies.yaml"
    add_company(path, "Infraspeak")
    registry = load_registry(path)
    assert find_company(registry, "Infraspeak, Lda")["name"] == "Infraspeak"
    assert find_company(registry, "INFRASPEAK S.A.")["name"] == "Infraspeak"
    assert find_company(registry, "Other") is None


def test_find_folds_accents(tmp_path):
    path = tmp_path / "companies.yaml"
    add_company(path, "Açoreana")
    assert find_company(load_registry(path), "acoreana ltd") is not None


def test_alias_match(tmp_path):
    path = tmp_path / "companies.yaml"
    add_company(path, "Infraspeak", aliases=["Infra Speak"])
    assert find_company(load_registry(path), "infra-speak, Lda")["name"] == "Infraspeak"


def test_sponsor_creates_company(tmp_path):
    path = tmp_path / "companies.yaml"
    entry = add_sponsor(path, "Acme Lda", type="pt-tech-visa", source="posts", day=date(2026, 10, 22))
    assert entry["name"] == "Acme Lda"
    registry = load_registry(path)
    assert registry[0]["sponsor"] == [{"type": "pt-tech-visa", "source": "posts", "date": "2026-10-22"}]
    assert "date: 2026-10-22" in path.read_text(encoding="utf-8")
    assert list(registry[0]) == ["name", "aliases", "careers_url", "ats", "sponsor", "notes"]


def test_sponsor_reuses_existing_company(tmp_path):
    path = tmp_path / "companies.yaml"
    add_company(path, "Infraspeak", ats="teamtailor")
    add_sponsor(path, "INFRASPEAK SA", type="pt-tech-visa", source="s", day=date(2026, 10, 22))
    registry = load_registry(path)
    assert len(registry) == 1 and registry[0]["ats"] == "teamtailor"


def test_add_company_updates_existing(tmp_path):
    path = tmp_path / "companies.yaml"
    add_sponsor(path, "Infraspeak", type="pt-tech-visa", source="s", day=date(2026, 10, 22))
    add_company(path, "Infraspeak", careers_url="https://careers.infraspeak.com", ats="teamtailor")
    registry = load_registry(path)
    assert len(registry) == 1
    assert registry[0]["careers_url"] == "https://careers.infraspeak.com"
    assert has_sponsor_mark(registry[0])


def test_has_sponsor_mark(tmp_path):
    path = tmp_path / "companies.yaml"
    plain = add_company(path, "Plain")
    assert not has_sponsor_mark(plain)
    assert not has_sponsor_mark(None)
    marked = add_sponsor(path, "Marked", type="nl-ind", source="s", day=date(2026, 10, 22))
    assert has_sponsor_mark(marked)


def test_bad_type_rejected(tmp_path):
    path = tmp_path / "companies.yaml"
    with pytest.raises(CompanyError):
        add_sponsor(path, "Acme", type="made-up", source="s", day=date(2026, 10, 22))
    assert not path.exists()
    with pytest.raises(CompanyError):
        add_company(path, "Acme", ats="nope")


def test_missing_file_is_empty_and_bad_file_rejected(tmp_path):
    path = tmp_path / "companies.yaml"
    assert load_registry(path) == []
    path.write_text(yaml.safe_dump([{"name": "X", "ats": "nope"}]), encoding="utf-8")
    with pytest.raises(CompanyError):
        load_registry(path)


def test_cli_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    assert main(["company", "sponsor", "Infraspeak", "--type", "pt-tech-visa",
                 "--source", "LinkedIn company posts", "--date", "2026-10-22"]) == 0
    assert main(["company", "add", "Infraspeak", "--careers", "https://careers.infraspeak.com",
                 "--ats", "teamtailor", "--alias", "Infra Speak"]) == 0
    capsys.readouterr()
    assert main(["company", "show", "infraspeak lda"]) == 0
    out = capsys.readouterr().out
    assert "teamtailor" in out and "pt-tech-visa" in out
    assert main(["company", "show", "nobody"]) == 1
    capsys.readouterr()
    assert main(["company", "sponsor", "X", "--type", "bad", "--source", "s"]) == 1
    assert "unknown sponsor type" in capsys.readouterr().err


def test_minimal_entry_works_everywhere(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    path = tmp_path / "companies.yaml"
    path.write_text("- name: Foo\n", encoding="utf-8")
    assert load_registry(path)[0] == {"name": "Foo", "aliases": [], "careers_url": None,
                                      "ats": None, "sponsor": [], "notes": ""}
    assert main(["company", "show", "Foo"]) == 0
    assert main(["company", "add", "Foo", "--alias", "Fu"]) == 0
    assert main(["company", "sponsor", "Foo", "--type", "nl-ind", "--source", "s"]) == 0
    capsys.readouterr()
    assert main(["company", "show", "Foo"]) == 0
    assert "nl-ind" in capsys.readouterr().out


def test_empty_name_key_rejected(tmp_path, capsys):
    path = tmp_path / "companies.yaml"
    with pytest.raises(CompanyError):
        add_company(path, "!!!")
    with pytest.raises(CompanyError):
        add_sponsor(path, "  ", type="nl-ind", source="s", day=date(2026, 10, 22))
    assert not path.exists()

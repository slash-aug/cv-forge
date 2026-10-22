import pytest

from cvforge.text import contains_term, fold, squash


def test_fold_is_nfkc_casefold():
    assert fold("Ｐroject") == "project"


def test_squash_drops_separators():
    assert squash("Project _-Zebra") == "projectzebra"


@pytest.mark.parametrize("text", ["Project Zebra", "project-zebra", "PROJECT_ZEBRA",
                                  "ｐｒｏｊｅｃｔｚｅｂｒａ"])
def test_contains_term_variants(text):
    assert contains_term(f"see {text} notes", "projectzebra")


def test_contains_term_blank_term_never_matches():
    assert not contains_term("anything", "  ")


def test_contains_term_clean_text():
    assert not contains_term("a zebra project", "projectzebra")


@pytest.mark.parametrize("text", ["AcmeCorp", "Acme Corp", "acme_corp"])
def test_hyphenated_term_keeps_separators_significant(text):
    assert not contains_term(f"worked at {text}", "acme-corp")


def test_hyphenated_term_matches_literally():
    assert contains_term("see ACME-CORP docs", "acme-corp")


def test_trailing_separator_term_needs_the_separator():
    assert not contains_term("Acme Payments", "ACME-")
    assert contains_term("ticket acme-123", "ACME-")

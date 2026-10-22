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

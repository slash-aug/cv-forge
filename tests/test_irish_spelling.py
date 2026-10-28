from cvforge.render.irish import irish_spelling


def test_spelling_basic():
    assert irish_spelling("Optimized and organized the color center") == "Optimised and organised the colour centre"


def test_spelling_skips_urls_and_keywords():
    assert irish_spelling("see https://x.io/color-analyzer", keep={"Analyzer"}) == "see https://x.io/color-analyzer"


def test_spelling_keeps_skill_keywords_outside_urls():
    assert irish_spelling("Used Color Picker to analyze", keep={"Color Picker"}) == "Used Color Picker to analyse"


def test_spelling_word_forms_and_case():
    text = ("ORGANIZATION standardizing modernized prioritize behavior catalog "
            "behaviors catalogs centered colors")
    assert irish_spelling(text) == (
        "ORGANISATION standardising modernised prioritise behaviour catalogue "
        "behaviours catalogues centred colours")


def test_spelling_word_boundaries_and_untouched_words():
    text = "datacenter program programming license recolorize"
    assert irish_spelling(text) == text

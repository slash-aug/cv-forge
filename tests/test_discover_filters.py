import pytest

from cvforge.discover.filters import (
    is_senior,
    is_software,
    market_of,
    master_keywords,
    refuses_sponsorship,
    stack_fit,
)


@pytest.mark.parametrize("loc,wp,desc,want", [
    ("Dublin, Ireland", "onsite", "", ("IE", False)),
    ("Cork", None, "", ("IE", False)),
    ("Remote - EMEA", "remote", "", ("IE", False)),
    ("San Francisco, CA", "onsite", "", (None, False)),
    ("Remote - US", "remote", "", (None, False)),
    ("Remote", "remote", "Open to candidates across Europe.", ("IE", False)),
    ("Remote", "remote", "We are a distributed team.", ("IE", True)),
    ("Londrina, PR, Brasil", "onsite", "", ("BR", False)),
    ("São Paulo, SP, Brasil", "hybrid", "", (None, False)),
    ("Brasil", "remote", "", ("BR", False)),
    ("Dublin; Remote - Brazil", "remote", "", ("IE", False)),
    ("Remote - Ireland", "remote", "", ("IE", False)),
    ("Remote, Canada", "remote", "", (None, False)),
    ("Anywhere", "remote", "Work from anywhere.", ("IE", True)),
    ("Anywhere", None, "Work from anywhere.", ("IE", True)),
    ("", "remote", "", ("IE", True)),
    ("Remote - Brazil", None, "", ("BR", False)),
])
def test_market_of(loc, wp, desc, want):
    assert market_of(loc, wp, desc, home="IE") == want


def test_market_ie_word_is_case_sensitive_and_location_only():
    assert market_of("Austin, TX", "onsite", "i.e. we ship; ie", home="IE") == (None, False)
    assert market_of("Galway, IE", "onsite", "", home="IE") == ("IE", False)


@pytest.mark.parametrize("title,want", [
    ("Software Engineer", False), ("Full Stack Developer II", False), ("Team Lead, Web", False),
    ("Senior Software Engineer", True), ("Sr. Frontend Engineer", True), ("Staff Engineer", True),
    ("Engineering Manager", True), ("Software Engineer III", True), ("Software Engineer (L5)", True),
    ("Senior Team Lead", True), ("Tech Lead", True), ("Desenvolvedor Sênior", True),
    ("Software Engineer, Leadership Tools", False), ("Software Engineer, Staffing Platform", False),
    ("Software Engineer, Seniority Team", False),
    ("Software Engineer E5", True), ("Software Engineer E3", False),
])
def test_is_senior_title(title, want):
    assert is_senior(title, "") is want


@pytest.mark.parametrize("desc,want", [
    ("You have 5+ years of experience", True), ("at least 6 years building", True),
    ("minimum of 7 years", True), ("3-5 years of experience", False), ("2+ years", False),
    ("Experiência de 5+ anos", True),
    ("5 or more years", True), ("min. 5 years", True), ("no mínimo 5 anos", True),
    ("pelo menos 5 anos", True), ("5-7 years", True),
])
def test_is_senior_years(desc, want):
    assert is_senior("Software Engineer", desc) is want


def test_is_software():
    assert is_software("Backend Engineer") and is_software("Desenvolvedora Full Stack")
    assert not is_software("Sales Engineer") and not is_software("Account Executive")
    assert not is_software("Technical Recruiter") and not is_software("Product Designer")
    assert is_software("Quality Assurance Software Engineer")
    assert not is_software("Quality Assurance Engineer")
    assert is_software("Front End Developer") and is_software("Dev Web")


def test_refuses_sponsorship():
    assert refuses_sponsorship("We are unable to sponsor visas for this role.")
    assert refuses_sponsorship("Candidates must have the right to work in Ireland.")
    assert refuses_sponsorship("We offer visa sponsorship and relocation.") is None
    assert refuses_sponsorship("We can sponsor work permits.") is None
    assert refuses_sponsorship("No visa sponsorship available")
    assert refuses_sponsorship("Sponsorship is not available")
    assert refuses_sponsorship("We can't sponsor")
    assert refuses_sponsorship("EU citizens only")
    assert refuses_sponsorship("Stamp 4 required")
    assert refuses_sponsorship("must be eligible to work in the EU without sponsorship")


KW = ["React", "TypeScript", "Node.js", "Next.js", "PostgreSQL", "React Native"]


def test_stack_fit_levels():
    assert stack_fit("React, TypeScript and Node.js on PostgreSQL", KW) == ("match", ["React", "TypeScript", "Node.js", "PostgreSQL"])
    assert stack_fit("We use Python and React", KW) == ("partial", ["React"])
    assert stack_fit("Any language; we care about fundamentals", KW) == ("partial", [])
    assert stack_fit("Embedded C on RTOS firmware", KW) == ("misaligned", [])
    assert stack_fit("Swift and SwiftUI, plus some React", KW)[0] == "partial"
    assert stack_fit("nodejs", KW) == ("partial", [])   # no fuzzy spelling: documented limit


def test_stack_fit_short_keywords_case_sensitive():
    assert stack_fit("let's go home", ["Go"]) == ("partial", [])
    assert stack_fit("Written in Go", ["Go"]) == ("partial", ["Go"])
    assert stack_fit("C# and C++ code", ["C#", "C++", "C"])[1] == ["C#", "C++"]


def test_stack_fit_foreign_in_master_ignored():
    assert stack_fit("SAP work", ["SAP"]) == ("partial", ["SAP"])


def test_master_keywords_dedup():
    m = {"skills": [{"keywords": ["React", "Node.js"]}, {"keywords": ["React", "SQL"]}]}
    assert master_keywords(m) == ["React", "Node.js", "SQL"]
    assert master_keywords({}) == []


@pytest.mark.parametrize("loc,wp", [
    ("Remote - Global", "remote"), ("Fully Remote", None), ("100% Remote", None),
    ("Remote-first", None), ("Remote - Anywhere in the world", None),
    ("Remote / Hybrid", None), ("International", "remote"),
    ("Anywhere", None), ("Worldwide", None), ("Global", None),
])
def test_market_remote_noise_words_are_no_restriction(loc, wp):
    assert market_of(loc, wp, "", home="IE") == ("IE", True)


def test_market_remote_noise_still_restricted_by_real_place():
    assert market_of("Remote - Global, US only", None, "", home="IE") == (None, False)


@pytest.mark.parametrize("text", [
    "Acme PLC is hiring a developer", "Apex Group builds products",
    "We move at swift pace", "engineers embedded in product teams",
])
def test_stack_fit_ambiguous_foreign_terms_alone_not_misaligned(text):
    assert stack_fit(text, KW)[0] == "partial"


def test_stack_fit_two_ambiguous_terms_misaligned():
    assert stack_fit("Embedded Swift on PLC", KW)[0] == "misaligned"


@pytest.mark.parametrize("desc", [
    "Must be at least 18 years old", "at least 21 years of age",
    "We have 15+ years in business", "25 years of history", "10+ years in the market",
])
def test_is_senior_ignores_non_experience_years(desc):
    assert is_senior("Software Engineer", desc) is False


@pytest.mark.parametrize("title", [
    "Frontend Developer, Customer Portal", "Backend Engineer - Process Automation",
    "Full Stack Developer, Field Services",
])
def test_is_software_strong_words_override_exclusions(title):
    assert is_software(title)


def test_is_software_weak_words_still_excluded():
    assert not is_software("Support Engineer") and not is_software("Sales Engineer")


def test_no_pathological_backtracking():
    blob = " " * 50_000 + "x"
    assert is_senior("Software Engineer", blob) is False
    assert refuses_sponsorship(blob) is None
    assert stack_fit(blob, KW) == ("partial", [])
    assert is_senior("Software Engineer", "5" + " " * 50_000 + "+" + " " * 50_000 + "x") is False


@pytest.mark.parametrize("text", [
    "If you do not need sponsorship, tick no",
    "we do not just sponsor, we relocate",
    "No sponsorship needed",
])
def test_refuses_sponsorship_negatives(text):
    assert refuses_sponsorship(text) is None


def test_refuses_sponsorship_new_forms():
    assert refuses_sponsorship("We do not currently sponsor visas")
    assert refuses_sponsorship("No sponsorship available")


def test_is_senior_level_v():
    assert is_senior("Software Engineer V", "") is True
    assert is_senior("Software Engineer (Remote) v", "") is False

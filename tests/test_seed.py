from cvforge.apply.companies import add_company, find_company, load_registry
from cvforge.apply.seed import seed_ie


def test_seed_adds_with_careers_url(tmp_path):
    r = seed_ie(tmp_path / "companies.yaml")
    reg = load_registry(tmp_path / "companies.yaml")
    stripe = find_company(reg, "Stripe")
    assert stripe["ats"] == "greenhouse"
    assert stripe["careers_url"] == "https://boards.greenhouse.io/stripe"
    assert stripe["sponsor"] == [] and r.added >= 100
    assert stripe["notes"] == "seed: JobPilot ireland preset 405f706"


def test_seed_never_overwrites(tmp_path):
    add_company(tmp_path / "c.yaml", "Stripe", careers_url="https://stripe.com/jobs", ats="other")
    r = seed_ie(tmp_path / "c.yaml")
    stripe = find_company(load_registry(tmp_path / "c.yaml"), "Stripe")
    assert stripe["careers_url"] == "https://stripe.com/jobs" and stripe["ats"] == "other"
    assert r.kept >= 1


def test_seed_is_idempotent(tmp_path):
    seed_ie(tmp_path / "c.yaml")
    again = seed_ie(tmp_path / "c.yaml")
    assert again.added == 0 and again.kept >= 100


def test_workday_url(tmp_path):
    seed_ie(tmp_path / "c.yaml")
    m = find_company(load_registry(tmp_path / "c.yaml"), "Mastercard")
    assert m["ats"] == "workday"
    assert m["careers_url"] == "https://mastercard.wd1.myworkdayjobs.com/CorporateCareers"


def test_other_ats_urls(tmp_path):
    seed_ie(tmp_path / "c.yaml")
    reg = load_registry(tmp_path / "c.yaml")
    assert find_company(reg, "Teamwork")["careers_url"] == "https://teamwork.jobs.personio.de"
    assert find_company(reg, "Davy")["careers_url"] == "https://apply.workable.com/davy"
    assert find_company(reg, "ServiceNow")["careers_url"] == "https://jobs.smartrecruiters.com/ServiceNow"
    assert find_company(reg, "OpenAI")["careers_url"] == "https://jobs.ashbyhq.com/openai"
    assert find_company(reg, "Pipedrive")["careers_url"] == "https://jobs.lever.co/pipedrive"

from datetime import date

import pytest

from cvforge.apply.ie_permits import load_permit_table
from cvforge.discover.filters import master_keywords
from cvforge.discover.permit import needs_rates, permit_outcome
from cvforge.discover.screen import screen
from cvforge.discover.sources import Role
from cvforge.money.rates import Rates

TABLE = load_permit_table(date(2026, 10, 28))[0]
RATES = Rates(day="2026-10-28", per_eur={"EUR": 1.0, "USD": 1.1})


def sal(lo, hi, cur="EUR", period="year"):
    return {"currency": cur, "min": lo, "max": hi, "period": period}


def role(title="Software Engineer", location="Dublin, Ireland", description="", salary=None,
         workplace=None):
    return Role("greenhouse", "acme", "1", "Acme", title, location, workplace,
                "https://example.com/1", description, salary)


def run(discover_master, r):
    return screen(r, home="IE", keywords=master_keywords(discover_master),
                  master=discover_master, table=TABLE, rates=None)


def test_range_kept_when_max_reaches_gep(discover_master):
    out = permit_outcome(sal(30000, 40000), discover_master, TABLE, None)
    assert out.drop is False and out.route == "gep"


def test_dropped_below_gep(discover_master):
    assert permit_outcome(sal(25000, 35000), discover_master, TABLE, None).drop


def test_never_csep_from_the_max_alone(discover_master):
    out = permit_outcome(sal(60000, 90000), discover_master, TABLE, None)
    assert out.route == "csep-if-degree"


def test_csep_when_min_clears_any_floor(discover_master):
    assert permit_outcome(sal(70000, 90000), discover_master, TABLE, None).route == "csep"


@pytest.mark.parametrize("salary", [None, sal(50000, None, period=""),
                                    sal(50000, 60000, cur="XYZ"),
                                    sal("competitive", None),
                                    sal(50000, None, period="fortnight"),
                                    sal(50000, None, period=None),
                                    sal(None, None)])
def test_unknown_salary_is_kept(discover_master, salary):
    out = permit_outcome(salary, discover_master, TABLE, RATES)
    assert out.drop is False and out.salary_unknown and out.route == "unknown"


def test_non_eur_without_rates_is_unknown(discover_master):
    out = permit_outcome(sal(44000, None, cur="USD"), discover_master, TABLE, None)
    assert out.salary_unknown and not out.drop


def test_usd_converted_with_rates(discover_master):
    # Converted for the drop gate only: a non-EUR salary never sets a route.
    out = permit_outcome(sal(44000, None, cur="USD"), discover_master, TABLE, RATES)
    assert out.drop is False and out.route == "unknown" and out.salary_unknown
    assert out.eur_max == pytest.approx(40000)


def test_needs_rates():
    assert needs_rates(None) is False
    assert needs_rates(sal(1, 2)) is False
    assert needs_rates(sal(1, 2, cur="usd")) is True
    assert needs_rates(sal(1, 2, period="month")) is True


def test_screen_out_of_market(discover_master):
    out = run(discover_master, role(location="San Francisco, CA"))
    assert out.drop == "out-of-market" and out.market is None and out.fit is None


def test_screen_not_software(discover_master):
    assert run(discover_master, role(title="Account Executive")).drop == "not-software"


def test_screen_senior(discover_master):
    assert run(discover_master, role(title="Senior Engineer")).drop == "senior"


def test_screen_no_sponsorship(discover_master):
    r = role(description="We are unable to sponsor visas.")
    assert run(discover_master, r).drop == "no-sponsorship"


def test_screen_misaligned(discover_master):
    r = role(title="Firmware Engineer", description="Embedded C on microcontrollers.")
    out = run(discover_master, r)
    assert out.drop == "misaligned" and out.fit == "misaligned"


def test_screen_below_permit(discover_master):
    r = role(title="Software Engineer", description="React TypeScript Node.js",
             salary=sal(30000, None))
    out = run(discover_master, r)
    assert out.drop == "below-permit" and out.market == "IE" and out.fit == "match"


def test_screen_shown_with_unknown_salary(discover_master):
    r = role(description="React TypeScript Node.js")
    out = run(discover_master, r)
    assert out.drop is None and out.fit == "match" and out.tags == ["salary unknown"]
    assert out.route == "unknown"


def test_screen_partial_tag_order(discover_master):
    r = role(description="We use React.", location="Remote")
    out = run(discover_master, r)
    assert out.drop is None
    assert out.tags == ["region unknown", "partial", "salary unknown"]


def test_screen_brazil_skips_permit_and_sponsorship(discover_master):
    r = role(location="Londrina, Brazil", description="No sponsorship available. React Node.js "
                                                       "TypeScript", salary=sal(1000, 2000))
    out = run(discover_master, r)
    assert out.market == "BR" and out.drop is None
    assert out.route is None and out.salary is None and "salary unknown" not in out.tags


def test_screen_bare_remote_is_home_with_region_unknown(discover_master):
    out = run(discover_master, role(location="Remote", description="React TypeScript Node.js"))
    assert out.market == "IE" and "region unknown" in out.tags


def test_swapped_range_routes_from_the_lower_figure(discover_master):
    out = permit_outcome(sal(90000, 60000), discover_master, TABLE, None)
    assert out.route == "csep-if-degree" and out.eur_min == 60000 and out.eur_max == 90000


def test_swapped_range_is_not_dropped_by_its_lower_figure(discover_master):
    assert not permit_outcome(sal(40000, 30000), discover_master, TABLE, None).drop


def test_zero_amount_is_unknown_not_dropped(discover_master):
    for s in (sal(0, None), sal(None, 0), sal(-5, None), sal(0, 0)):
        out = permit_outcome(s, discover_master, TABLE, None)
        assert out.salary_unknown and not out.drop


def test_zero_min_with_real_max_uses_the_max(discover_master):
    out = permit_outcome(sal(0, 50000), discover_master, TABLE, None)
    assert out.drop is False and not out.salary_unknown and out.route == "csep-if-degree"
    assert out.eur_max == 50000


CAD_RATES = Rates(day="2026-10-28", per_eur={"EUR": 1.0, "CAD": 1.5})


def test_non_eur_salary_never_shows_a_route(discover_master):
    out = permit_outcome(sal(215000, 270000, cur="CAD"), discover_master, TABLE, CAD_RATES)
    assert out.route == "unknown" and out.salary_unknown and out.drop is False


def test_non_eur_salary_still_dropped_below_permit(discover_master):
    assert permit_outcome(sal(20000, 30000, cur="USD"), discover_master, TABLE, RATES).drop


def test_eur_monthly_salary_keeps_its_route(discover_master):
    out = permit_outcome(sal(7000, 8000, period="month"), discover_master, TABLE, RATES)
    assert out.route == "csep" and not out.salary_unknown


def test_screen_non_eur_salary_tagged_unknown_and_shown_as_posted(discover_master):
    r = role(description="React, TypeScript and Node.js", salary=sal(215000, 270000, cur="CAD"))
    out = screen(r, home="IE", keywords=master_keywords(discover_master), master=discover_master,
                 table=TABLE, rates=CAD_RATES)
    assert out.drop is None and out.route == "unknown" and "salary unknown" in out.tags
    assert r.salary == sal(215000, 270000, cur="CAD")


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), "nan", "inf"])
def test_non_finite_amount_is_missing(discover_master, amount):
    out = permit_outcome(sal(amount, None), discover_master, TABLE, None)
    assert out.salary_unknown and not out.drop
    out = permit_outcome(sal(amount, 50000), discover_master, TABLE, None)
    assert out.eur_min == 50000 and out.eur_max == 50000 and not out.drop

from datetime import date

from cvforge.apply.ie_permits import load_permit_table


def test_table_in_force_on_2026_10_27():
    t, warnings = load_permit_table(date(2026, 10, 27))
    assert (t.csep_csol_degree, t.csep_any, t.gep) == (40904, 68911, 36605)
    assert (t.csep_min_months, t.gep_min_months) == (24, 12)
    assert {"2136", "2137", "1136", "2133", "2134", "2135", "2139"} <= t.csol_soc
    assert "3131" not in t.csol_soc
    assert t.source.startswith("https://enterprise.gov.ie/")
    assert warnings == []


def test_entry_before_march_2026_uses_old_floors():
    t, _ = load_permit_table(date(2026, 2, 1))
    assert (t.csep_csol_degree, t.csep_any) == (38000, 64000)


def test_stale_table_warns():
    _, warnings = load_permit_table(date(2027, 3, 2))
    assert warnings == ["Irish permit thresholds last updated 2026-03-01; check enterprise.gov.ie for newer figures"]

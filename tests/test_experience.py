from datetime import date
from pathlib import Path

from cvforge.apply.experience import engineering_months, years_limit
from cvforge.profile.model import load_master

PERSONA = Path(__file__).resolve().parent.parent / "examples" / "persona"
TODAY = date(2026, 10, 22)


def _job(job_id, positions, category=None):
    job = {
        "id": job_id,
        "name": job_id,
        "positions": [
            {"id": f"p-{job_id}-{i}", "startDate": s, "endDate": e}
            for i, (s, e) in enumerate(positions)
        ],
    }
    if category:
        job["x-category"] = category
    return job


def master_with(*jobs):
    return {"work": list(jobs)}


def test_overlapping_positions_merge():
    master = master_with(
        _job("a", [("2025-05", "2026-06"), ("2025-08", "2026-06")]),
        _job("b", [("2026-06", None)]),
    )
    assert engineering_months(master, TODAY) == 17


def test_other_category_excluded():
    base = _job("a", [("2025-05", "2026-06")], "engineering")
    other = _job("c", [("2023-05", "2024-07")], "other")
    assert engineering_months(master_with(base, other), TODAY) == engineering_months(
        master_with(base), TODAY
    )
    assert engineering_months(master_with(other), TODAY) == 0


def test_missing_category_counts():
    master = master_with(_job("a", [("2025-05", "2026-06")]))
    assert engineering_months(master, TODAY) == 14


def test_years_limit_values():
    assert years_limit(17) == 3 and years_limit(15) == 3
    assert years_limit(9) == 2 and years_limit(0) == 0


def test_persona_validates_with_category():
    master = load_master(PERSONA / "master.yaml")
    cats = {w["id"]: w.get("x-category") for w in master["work"]}
    assert cats["w-cafe-shift"] == "other"
    assert all(v == "engineering" for k, v in cats.items() if k != "w-cafe-shift")


def test_persona_engineering_months_ignores_cafe():
    master = load_master(PERSONA / "master.yaml")
    assert engineering_months(master, TODAY) == 81

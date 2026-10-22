import csv
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from cvforge import cli
from cvforge.apply import http as apply_http
from cvforge.apply.posting import Posting
from cvforge.money.normalise import Money
from cvforge.money.rates import Rates
from cvforge.salary.market import MARKET_COLUMNS, load_market, match_market
from cvforge.salary.suggest import suggest

TODAY = date(2026, 10, 22)
RATES = Rates("2026-10-21", {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85})
ROOT = Path(__file__).resolve().parents[1]
PERSONA = ROOT / "examples" / "persona" / "master.yaml"
TEMPLATE = ROOT / "examples" / "salary" / "market.template.csv"
FLOOR = Money(3000, "BRL", "month")


def row(**over):
    base = {"role": "frontend engineer", "seniority": "any", "country": "BR",
            "currency": "BRL", "period": "month", "low": "10000", "mid": "12000",
            "high": "15000", "source": "example", "year": "2026"}
    return {**base, **over}


def posted(lo, hi, cur="USD", period="month", contract="pj"):
    return {"min": lo, "max": hi, "currency": cur, "period": period,
            "contract": contract, "quote": "q"}


def test_posting_range_upper_middle():
    # 4500 + 0.75 * 3000 = 6750, rounded to the nearest 100 (pinned rule) = 6800
    s = suggest(posted(4500, 7500), [], FLOOR, RATES, clt_factor=1.4)
    assert s.basis == "posting"
    assert (s.amount, s.currency, s.period) == (6800, "USD", "month")
    assert s.brl_month == pytest.approx(6800 / 1.10 * 6.00)
    assert s.eur_year == pytest.approx(6800 / 1.10 * 12)
    assert s.usd_year == pytest.approx(6800 * 12)
    assert s.sources == ["q"]


def test_market_range_when_posting_silent():
    rows = [row(low="10000", high="15000"), row(low="9000", high="14000", source="b")]
    s = suggest(None, rows, FLOOR, RATES, clt_factor=1.4)
    assert s.basis == "market"
    assert (s.currency, s.period) == ("BRL", "month")
    assert s.amount == 13500  # 9000 + 0.75 * (15000 - 9000)
    assert any("example" in x for x in s.sources) and any("b" in x for x in s.sources)


def test_market_range_is_lowest_low_to_highest_high():
    rows = [row(low="10000", high="12000"), row(low="8000", high="16000")]
    s = suggest({"min": None, "max": None}, rows, FLOOR, RATES, clt_factor=1.4)
    assert s.amount == 14000


def test_floor_lifts_low_value():
    floor = Money(5000, "USD", "month")
    s = suggest(posted(1000, 2000, "USD"), [], floor, RATES, clt_factor=1.4)
    assert s.amount >= 5000
    assert s.brl_month >= 5000 / 1.10 * 6.00 - 1e-6


def test_floor_is_basis_when_nothing_else():
    s = suggest(None, [], Money(3000, "EUR", "month"), RATES, clt_factor=1.4)
    assert s.basis == "floor"
    assert s.amount == 3000 and s.currency == "EUR"


def test_rounding_to_100():
    s = suggest(posted(4000, 5003), [], FLOOR, RATES, clt_factor=1.4)
    assert s.amount % 100 == 0
    assert s.amount == 4800  # 4000 + 0.75 * 1003 = 4752.25


def test_match_market():
    rows = [row(), row(country="PT"), row(role="data scientist"),
            row(seniority="senior"), row(seniority="junior")]
    title = "Senior Frontend Engineer"
    got = match_market(rows, role=title, seniority="senior", country="BR")
    assert got == [rows[0], rows[3]]


def test_match_role_words_folded():
    rows = [row(role="Engenheiro Sênior")]
    title = "ENGENHEIRO senior de Plataforma"
    assert match_market(rows, role=title, seniority="any", country="BR") == rows
    assert match_market(rows, role="Engenheiro de Plataforma", seniority="any",
                        country="BR") == []


def test_template_columns_match():
    with TEMPLATE.open(encoding="utf-8", newline="") as fh:
        assert tuple(next(csv.reader(fh))) == MARKET_COLUMNS
    rows = load_market(TEMPLATE)
    assert rows and all(r["source"] == "example" for r in rows)


def test_missing_market_file(tmp_path):
    assert load_market(tmp_path / "nope.csv") == []


# CLI


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CVFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)

    def no_net(url, **kw):
        raise apply_http.FetchError("network must not be used")

    monkeypatch.setattr(apply_http, "get", no_net)
    (tmp_path / "salary").mkdir()
    (tmp_path / "salary" / f"ecb-{TODAY.isoformat()}.json").write_text(
        json.dumps({"day": RATES.day, "per_eur": RATES.per_eur}), encoding="utf-8")
    app = tmp_path / "applications" / "acme-frontend"
    Posting(company="Acme", title="Senior Frontend Engineer", location="", location_requirements=[],
            workplace="remote", salary=None, language="en", url="https://x.test/1",
            apply_url=None, source="manual", fetched="2026-10-22", description="d").save(app)
    (app / "requirements.yaml").write_text(yaml.safe_dump({
        "years": [], "location": {"workplace": "remote", "job_countries": ["BR"], "allowed": ["Brazil"]},
        "sponsorship": {"status": "silent"},
        "salary": {"min": 4500, "max": 7500, "currency": "USD", "period": "month",
                   "contract": "pj", "quote": "USD 4500 to 7500"},
    }), encoding="utf-8")
    return app


def _run(*args):
    return cli.main(["salary", "acme-frontend", "--master", str(PERSONA),
                     "--market", "/nonexistent.csv", *args])


def test_cli_writes_unconfirmed(env, capsys):
    assert _run() == 0
    out = capsys.readouterr().out
    assert "6,800" in out and "BRL" in out and "EUR" in out and "USD" in out
    data = json.loads((env / "salary.json").read_text(encoding="utf-8"))
    assert data["confirmed"] is False and data["amount"] == 6800


def test_confirm_writes_flag(env):
    assert _run("--confirm") == 0
    data = json.loads((env / "salary.json").read_text(encoding="utf-8"))
    assert data["confirmed"] is True and data["amount"] == 6800


def test_confirm_replaces_amount(env):
    assert _run("--confirm", "7000") == 0
    data = json.loads((env / "salary.json").read_text(encoding="utf-8"))
    assert data["confirmed"] is True and data["amount"] == 7000
    assert data["usd_year"] == pytest.approx(84000)


def test_unknown_slug(env):
    assert cli.main(["salary", "nope", "--master", str(PERSONA)]) == 1

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
from cvforge.salary.market import MARKET_COLUMNS, MarketError, load_market, match_market
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


# Fix round 1


def test_clt_posting_lifted_to_floor_exact():
    # CLT 1000-1500 BRL/month -> 1375 -> 1400; x1.4 = 1960 < 3000; lifted: 3000 / 1.4 = 2142.9 -> 2200
    s = suggest(posted(1000, 1500, "BRL", contract="clt"), [], FLOOR, RATES, clt_factor=1.4)
    assert s.amount == 2200
    assert s.amount * 1.4 >= 3000
    assert "lifted to payFloor" in s.sources


def test_clt_posting_above_floor_not_lifted():
    s = suggest(posted(3000, 5000, "BRL", contract="clt"), [], FLOOR, RATES, clt_factor=1.4)
    assert s.amount == 4500


def test_yearly_posting_lifted_to_floor_exact():
    # 12000-18000 BRL/year -> 16500/year = 1375/month < 3000; floor 36000/year
    s = suggest(posted(12000, 18000, "BRL", "year"), [], FLOOR, RATES, clt_factor=1.4)
    assert (s.amount, s.period) == (36000, "year")
    assert s.brl_month == pytest.approx(3000)


def _set_req(app, **salary):
    path = app / "requirements.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["salary"] = {"min": None, "max": None, "currency": None, "period": None,
                      "contract": "unknown", "quote": None, **salary}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_cli_floor_path(env, capsys):
    _set_req(env)
    assert _run() == 0
    out = capsys.readouterr().out
    data = json.loads((env / "salary.json").read_text(encoding="utf-8"))
    assert data["basis"] == "floor"
    assert (data["amount"], data["currency"], data["period"]) == (3000, "EUR", "month")
    assert "Suggested (floor): 3,000 EUR/month" in out and "payFloor" in out


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "0", "-5", "abc"])
def test_confirm_rejects_bad_amount(env, capsys, bad):
    assert _run(f"--confirm={bad}") == 1
    assert "invalid amount" in capsys.readouterr().err
    assert not (env / "salary.json").exists()


def test_confirm_below_floor_warns_but_writes(env, capsys):
    # persona floor 3000 EUR/month; 1000 USD/month is far below
    assert _run("--confirm", "1000") == 0
    err = capsys.readouterr().err
    assert "below" in err and "floor" in err and "3000" in err
    data = json.loads((env / "salary.json").read_text(encoding="utf-8"))
    assert data["confirmed"] is True and data["amount"] == 1000


def test_confirm_above_floor_no_warning(env, capsys):
    assert _run("--confirm", "7000") == 0
    assert capsys.readouterr().err == ""


def test_confirm_below_floor_uses_clt_basis(env, capsys):
    _set_req(env, min=2000, max=2000, currency="EUR", period="month", contract="clt",
             quote="x")
    # 2200 EUR x 1.4 = 3080 >= 3000: no warning; 2100 x 1.4 = 2940 < 3000: warning
    assert _run("--confirm", "2200") == 0
    assert capsys.readouterr().err == ""
    assert _run("--confirm", "2100") == 0
    assert "below" in capsys.readouterr().err


def test_no_confirm_no_amount_error(env, capsys):
    assert _run() == 0
    assert "invalid amount" not in capsys.readouterr().err


def _market(tmp_path, body):
    p = tmp_path / "m.csv"
    p.write_text(",".join(MARKET_COLUMNS) + "\n" + body, encoding="utf-8")
    return p


def test_market_non_numeric_names_file_and_row(tmp_path):
    p = _market(tmp_path, "a,any,BR,BRL,month,1,2,3,s,2026\nb,any,BR,BRL,month,x,2,3,s,2026\n")
    with pytest.raises(MarketError) as exc:
        load_market(p)
    assert "m.csv" in str(exc.value) and "row 3" in str(exc.value) and "low" in str(exc.value)


def test_market_missing_columns(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("role,country\nx,BR\n", encoding="utf-8")
    with pytest.raises(MarketError) as exc:
        load_market(p)
    assert "m.csv" in str(exc.value) and "low" in str(exc.value)


def test_cli_market_error_exit_1(env, tmp_path, capsys):
    p = _market(tmp_path, "frontend engineer,any,BR,BRL,month,oops,2,3,s,2026\n")
    assert cli.main(["salary", "acme-frontend", "--master", str(PERSONA),
                     "--market", str(p)]) == 1
    assert "m.csv" in capsys.readouterr().err

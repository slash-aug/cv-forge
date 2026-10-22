import json
from datetime import date
from pathlib import Path

import pytest

from cvforge.apply.http import FetchError
from cvforge.config import load_config
from cvforge.money.normalise import Money, annual, monthly, pj_equivalent
from cvforge.money.rates import MoneyError, Rates, convert, load_rates, parse_ecb

XML = (Path(__file__).parent / "fixtures" / "ecb_daily.xml").read_text()
RATES = Rates("2026-10-21", {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85})
TODAY = date(2026, 10, 22)


def _no_net(url, **kw):
    raise AssertionError("network must not be used")


def _fail(url, **kw):
    raise FetchError("down")


def test_parse_ecb():
    r = parse_ecb(XML)
    assert r.day == "2026-10-21"
    assert r.per_eur == {"EUR": 1.0, "USD": 1.10, "BRL": 6.00, "GBP": 0.85}


def test_convert_brl_usd_via_eur():
    assert convert(6000, "BRL", "USD", RATES) == pytest.approx(1100.0)
    assert convert(5, "EUR", "EUR", RATES) == 5


def test_monthly_from_year_and_hour():
    assert monthly(Money(120000, "BRL", "year"), "BRL", RATES) == pytest.approx(10000)
    assert monthly(Money(10, "EUR", "hour"), "EUR", RATES) == pytest.approx(1680)
    assert monthly(Money(6000, "BRL", "month"), "USD", RATES) == pytest.approx(1100)
    assert annual(Money(1000, "EUR", "month"), "EUR", RATES) == pytest.approx(12000)
    with pytest.raises(ValueError):
        monthly(Money(1, "EUR", "week"), "EUR", RATES)


def test_cache_used_without_fetch(tmp_path):
    (tmp_path / "ecb-2026-10-22.json").write_text(
        json.dumps({"day": "2026-10-22", "per_eur": {"EUR": 1.0, "USD": 2.0}})
    )
    r = load_rates(tmp_path, TODAY, _no_net)
    assert r.per_eur["USD"] == 2.0


def test_fetch_writes_cache(tmp_path):
    cache = tmp_path / "salary"
    r = load_rates(cache, TODAY, lambda url, **kw: XML)
    assert r.per_eur["BRL"] == 6.00
    assert (cache / "ecb-2026-10-22.json").exists()


def test_fetch_failure_falls_back_to_newest_cache(tmp_path, capsys):
    for d, usd in (("2026-10-18", 1.5), ("2026-10-20", 1.7)):
        (tmp_path / f"ecb-{d}.json").write_text(
            json.dumps({"day": d, "per_eur": {"EUR": 1.0, "USD": usd}})
        )
    r = load_rates(tmp_path, TODAY, _fail)
    assert r.per_eur["USD"] == 1.7
    assert "warning" in capsys.readouterr().err


def test_no_cache_and_no_network_raises(tmp_path):
    with pytest.raises(MoneyError):
        load_rates(tmp_path / "none", TODAY, _fail)


def test_pj_equivalent_only_for_clt():
    assert pj_equivalent(10000, "clt", 1.4) == pytest.approx(14000)
    assert pj_equivalent(10000, "pj", 1.4) == 10000
    assert pj_equivalent(10000, "other", 1.4) == 10000


def test_clt_factor_config(tmp_path):
    assert load_config(env={}, file=tmp_path / "m.toml").clt_factor == 1.4
    assert load_config(env={"CVFORGE_CLT_FACTOR": "1.25"}, file=None).clt_factor == 1.25
    with pytest.raises(ValueError, match="clt_factor"):
        load_config(env={"CVFORGE_CLT_FACTOR": "abc"}, file=None)

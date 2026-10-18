import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from invest.analysis.indicators import indicators, validate_bars, align_relative
from invest.analysis.risk import size_position, value_position, fee
from invest.analysis.selection import strategy_for
from invest.db import transaction
from invest.models import Dataset, Quote


def frame(count=80):
    close = np.arange(1, count + 1, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 0.5, "close": close, "volume": 1000}
    )


def test_indicator_reference_values_and_warmup():
    result = indicators(frame())
    assert result.ma5.iloc[-1] == 78
    assert result.ma20.iloc[-1] == 70.5
    assert result.ma60.iloc[-1] == 50.5
    assert result.ma60.iloc[:59].isna().all()
    assert result.rsi.iloc[14] == 100
    assert result.rsi.iloc[:14].isna().all()
    assert result.atr.iloc[13] == pytest.approx((1.5 + 13 * 2) / 14)
    assert result.return5.iloc[-1] == pytest.approx((80 / 75 - 1) * 100)
    assert result.volume_ratio.iloc[-1] == 1


def test_flat_rsi_and_missing_history_are_explicit():
    f = frame()
    f["close"] = 10
    f["open"] = 10
    f["high"] = 11
    f["low"] = 9
    assert indicators(f).rsi.iloc[-1] == 50
    assert validate_bars(f.head(20))
    f.loc[30, "close"] = np.nan
    assert any("결측" in e for e in validate_bars(f))
    assert len(indicators(frame().head(10))) == 10


def test_indicators_cannot_see_future():
    f = frame()
    before = indicators(f.head(65)).iloc[-1]
    f.loc[65:, "close"] = 5000
    after = indicators(f).iloc[64]
    for name in ["ma5", "ma20", "ma60", "rsi", "atr", "return20"]:
        assert before[name] == after[name]


def test_relative_returns_align_sessions_not_row_numbers():
    a = frame(80)
    a["session"] = pd.date_range("2025-01-01", periods=80).astype(str)
    b = a.copy()
    b["close"] = 100
    assert align_relative(a, b, 5) == pytest.approx((80 / 75 - 1) * 100)
    assert align_relative(a, b.iloc[:-1], 5) is None


def test_risk_includes_cost_cash_and_concentration():
    r = size_position(
        entry=100, stop=95, target=112, cash=10000, equity=10000, budget=5000, max_weight=0.2, loss_budget=50
    )
    assert r["quantity"] == 9
    assert r["planned_loss"] <= 50
    assert r["stress_loss"] > r["planned_loss"]
    concentrated = size_position(
        entry=100,
        stop=95,
        target=112,
        cash=10000,
        equity=10000,
        budget=5000,
        max_weight=0.2,
        loss_budget=50,
        existing_value=2000,
    )
    assert concentrated["quantity"] == 0
    assert (
        size_position(
            entry=100, stop=100, target=99, cash=100, equity=100, budget=100, max_weight=1, loss_budget=50
        )["quantity"]
        == 0
    )
    assert fee(100, 10) == 1


def test_fx_pnl_and_bid_liquidation_are_distinct():
    r = value_position(10, 100, 110, 109, 1, 1300, 1400)
    assert r["pnl_usd"] == 99
    assert r["pnl_krw"] == 1100 * 1400 - 1001 * 1300
    assert r["fx_component_krw"] == 110000
    assert r["liquidation_pnl_usd"] < r["pnl_usd"]


@pytest.mark.parametrize(
    "days,key", [(2, "short"), (5, "short"), (6, "medium"), (10, "medium"), (11, "long"), (20, "long")]
)
def test_period_strategies(days, key):
    assert strategy_for(days)[0] == key


def test_one_day_is_unsupported():
    with pytest.raises(ValueError):
        strategy_for(1)


def test_research_provenance_and_no_probability(research):
    assert len(research["shortlist"]) <= 5
    for c in research["candidates"]:
        assert c["probability"] == "산출하지 않음"
        assert c["source"] == "synthetic-v1"
        assert len(c["reasons"]) == 3 and len(c["risks"]) >= 3
    assert research["mode"] == "demo"


def test_excessive_target_does_not_force_candidates(owner):
    prefs = owner.get("/api/settings").json()
    prefs.pop("budget_usd")
    prefs["target_pct"] = 80
    assert owner.put("/api/settings", json=prefs).status_code == 200
    result = owner.post("/api/research").json()
    assert not result["shortlist"]
    assert all(c["status"] == "매수 보류" for c in result["candidates"])


def test_unknown_halt_and_missing_bars_fail_closed(owner):
    with transaction() as db:
        q = db.scalar(select(Quote).limit(1))
        q.quality = {**q.quality, "halt_clear": None}
        id = q.instrument_id
    r = owner.post("/api/research").json()
    c = next(c for c in r["candidates"] if c["id"] == id)
    assert c["status"] == "데이터 부족"
    with transaction() as db:
        ds = db.get(Dataset, id)
        ds.bars = ds.bars[:20]
    assert id not in owner.post("/api/research").json()["shortlist"]


def test_manual_existing_holdings_count_toward_limits(owner):
    p = owner.get("/api/settings").json()
    p.pop("budget_usd")
    p.update(max_positions=1, existing_holdings=[{"instrument_id": "cik:0000320193", "quantity": 2}])
    assert owner.put("/api/settings", json=p).status_code == 200
    r = owner.post("/api/research").json()
    assert not r["shortlist"]

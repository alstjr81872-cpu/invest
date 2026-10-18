import tomllib
from pathlib import Path

import pandas as pd

from .indicators import indicators, validate_bars, align_relative
from .risk import cents, size_position

CONFIG = tomllib.loads((Path(__file__).parents[1] / "strategies.toml").read_text())


def strategy_for(days: int):
    if not 2 <= days <= 20:
        raise ValueError("2~20 거래일만 지원합니다. 1일 이내 분석은 미지원입니다.")
    key = "short" if days <= 5 else "medium" if days <= 10 else "long"
    return key, CONFIG[key]


def market_summary(frame: pd.DataFrame | None, source: str) -> dict:
    if frame is None or validate_bars(frame):
        return {"state": "판단 불가", "name": source, "facts": [], "interpretation": "필수 시장 데이터 부족"}
    r = indicators(frame).iloc[-1]
    state = "상승" if r.close > r.ma20 > r.ma60 else "하락" if r.close < r.ma20 < r.ma60 else "횡보"
    return {
        "state": state,
        "name": source,
        "facts": [f"20일 수익률 {r.return20:+.2f}%", f"20일 평균 {r.ma20:.2f} / 60일 평균 {r.ma60:.2f}"],
        "interpretation": f"종가와 이동평균 배열에 따른 {state} 분류",
        "last_session": str(r.session),
    }


def evaluate(
    instrument: dict,
    bars: list,
    market: list,
    sector: list,
    quote: dict,
    preferences: dict,
    funds: dict,
    quality: dict,
) -> dict:
    frame, bench, industry = pd.DataFrame(bars), pd.DataFrame(market), pd.DataFrame(sector)
    result = {
        **instrument,
        "status": "데이터 부족",
        "score": None,
        "probability": "산출하지 않음",
        "reasons": [],
        "risks": [],
        "risk": {"quantity": 0},
        "indicators": {},
        "strategy_version": CONFIG["version"],
        "evidence": "미검증 규칙 가설",
        "holding_days": preferences["holding_days"],
        "price": quote.get("last"),
        "as_of": quote.get("observed_at"),
        "source": quote.get("source"),
    }
    errors = validate_bars(frame)
    for field in ["halt_clear", "warning_clear", "corporate_actions_clear", "events_clear"]:
        if quality.get(field) is not True:
            errors.append(f"필수 위험 정보 미확인: {field}")
    if quality.get("quote_usable") is not True:
        errors.append("장중 시세 최신성·호가·지연 권한 미확인")
    if quality.get("daily_usable") is not True:
        errors.append("최신 완성 거래일 일봉이 없습니다.")
    if errors:
        return {**result, "risks": errors}
    key, rule = strategy_for(preferences["holding_days"])
    result["strategy"] = {"short": "단기 추세", "medium": "추세 지속", "long": "중기 구조"}[key]
    r = indicators(frame).iloc[-1]
    relative = align_relative(frame, bench, rule["lookback"])
    sector_relative = align_relative(frame, industry, rule["lookback"])
    ms = market_summary(bench, "시장 기준")
    if relative is None or sector_relative is None or ms["state"] == "판단 불가":
        return {**result, "risks": ["시장·업종 기준 데이터 부족"]}
    last = float(quote["last"])
    entry = float(cents(last))
    stop = float(cents(max(r.support, entry - rule["stop_atr"] * r.atr)))
    target_unconstrained = entry + rule["target_atr"] * r.atr
    target = float(cents(min(target_unconstrained, r.resistance)))
    risk = size_position(
        entry=entry,
        stop=stop,
        target=target,
        cash=funds["cash"],
        equity=funds["equity"],
        budget=preferences["budget_usd"],
        max_weight=preferences["max_weight"],
        loss_budget=preferences["loss_budget_usd"],
        existing_value=funds.get("existing_value", 0),
        sector_value=funds.get("sector_value", 0),
    )
    trend = max(0, min(50, (25 if r.close > r.ma20 > r.ma60 else 0) + min(25, max(0, relative * 5))))
    volume = min(25, max(0, float(r.volume_ratio) * 15))
    structure = 25 if target > entry and 35 <= r.rsi <= 72 else 5
    score = round(trend + volume + structure)
    dollar_volume = float((frame.close * frame.volume).tail(20).mean())
    suitable = risk.get("quantity", 0) > 0 and risk.get("risk_reward", 0) >= CONFIG["minimum_risk_reward"]
    excessive = preferences["target_pct"] > risk.get("net_gain_pct", 0)
    status = "조건 충족 시 진입 검토" if suitable and not excessive and score >= 55 else "관심 관찰"
    if excessive or ms["state"] == "하락" or dollar_volume < CONFIG["minimum_daily_dollar_volume"]:
        status = "매수 보류"
    risks = [
        "합성 데이터의 결과는 실제 종목 추천이나 전략 수익 검증이 아닙니다."
        if quality.get("demo")
        else "가격 규칙의 독립 검증이 완료되지 않았습니다.",
        "목표가가 20일 저항에 제한됩니다."
        if target < target_unconstrained
        else "목표 도달 전 반전·갭 위험이 있습니다.",
        "실제 뉴스·공시·실적 일정 확인 불가"
        if quality.get("demo")
        else "알려지지 않은 사건 위험이 남아 있습니다.",
    ]
    if excessive:
        risks.insert(0, "조건 부적합: 목표 순수익률이 기간·변동성·저항·비용 조건을 초과합니다.")
    return {
        **result,
        "status": status,
        "score": score,
        "entry": entry,
        "stop": stop,
        "target": target,
        "risk": risk,
        "components": {
            "추세·상대강도": round(trend),
            "거래량·유동성": round(volume),
            "기간·가격구조": structure,
        },
        "indicators": {
            k: round(float(r[k]), 4)
            for k in [
                "ma5",
                "ma20",
                "ma60",
                "rsi",
                "atr",
                "volume_ratio",
                "return5",
                "return10",
                "return20",
                "support",
                "resistance",
            ]
        },
        "relative_market": round(relative, 2),
        "relative_sector": round(sector_relative, 2),
        "reasons": [
            f"시장 대비 {rule['lookback']}일 상대수익률 {relative:+.2f}%",
            f"거래량은 20일 평균의 {r.volume_ratio:.2f}배 · 거래대금 ${dollar_volume:,.0f}",
            f"ATR(일평균 변동폭) ${r.atr:.2f}로 계산한 {preferences['holding_days']}거래일 가격 구조",
        ],
        "risks": risks,
        "rules": {
            "entry": "다음 유효한 합성 매도호가가 진입 허용 범위 안일 때 지정가 검토",
            "no_chase": f"표시가격 대비 0.5% 초과 추격 금지 / 최대 ${entry * 1.005:.2f}",
            "invalidation": "20일 추세 이탈·필수 데이터 부실·사건 위험 발생 시 무효",
            "expiry": "분석 생성 후 15분 이내, 주문 대기는 15분 후 취소",
            "holding_exit": "최초 체결 기준 보유 만료일에 사용자 청산 검토; 자동 주문 없음",
        },
    }

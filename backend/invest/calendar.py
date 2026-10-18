from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd


@lru_cache
def nyse():
    return xcals.get_calendar("XNYS", start="2000-01-01", end="2035-12-31")


def session_info(at: datetime) -> dict:
    stamp = pd.Timestamp(at)
    if stamp.tzinfo is None:
        raise ValueError("UTC-aware timestamps required")
    local = stamp.tz_convert("America/New_York")
    day = pd.Timestamp(local.date())
    cal = nyse()
    result = {
        "state": "closed",
        "label": "휴장 / 장 마감",
        "new_york": local.isoformat(),
        "seoul": stamp.tz_convert("Asia/Seoul").isoformat(),
        "early_close": False,
    }
    if cal.is_session(day):
        opened, closed = cal.session_open(day), cal.session_close(day)
        result.update(
            open=opened.isoformat(),
            close=closed.isoformat(),
            early_close=(closed - opened).total_seconds() < 23400,
        )
        if opened <= stamp < closed:
            result.update(state="regular", label="정규장")
        elif 4 <= local.hour and stamp < opened:
            result.update(state="pre", label="프리마켓 · 주문 미지원")
        elif closed <= stamp and local.hour < 20:
            result.update(state="post", label="애프터마켓 · 주문 미지원")
    return result


def demo_clock(now: datetime) -> datetime:
    """Explicit simulated regular session, independent of wall-clock market closure."""
    day = pd.Timestamp(now.astimezone(ZoneInfo("America/New_York")).date())
    cal = nyse()
    label = cal.date_to_session(day, direction="previous")
    return (
        cal.session_open(label) + pd.Timedelta(hours=1, seconds=int(now.timestamp()) % 1800)
    ).to_pydatetime()


def holding_end(at: datetime, days: int) -> datetime:
    cal = nyse()
    day = pd.Timestamp(at.astimezone(ZoneInfo("America/New_York")).date())
    session = cal.date_to_session(day, direction="next")
    return cal.session_close(cal.session_offset(session, days - 1)).to_pydatetime()


def completed_sessions(at: datetime, count: int = 260):
    cal = nyse()
    day = pd.Timestamp(at.astimezone(ZoneInfo("America/New_York")).date())
    label = cal.date_to_session(day, direction="previous")
    if cal.session_close(label) > pd.Timestamp(at):
        label = cal.previous_session(label)
    return cal.sessions_window(label, -count)

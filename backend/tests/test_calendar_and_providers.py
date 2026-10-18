from datetime import datetime, timedelta
import httpx
import pytest
from sqlalchemy import select

from invest.calendar import session_info, holding_end, completed_sessions
from invest.db import utcnow, transaction
from invest.models import Quote, Instrument
from invest.service import ingest_quote
from invest.providers.demo import quote, history
from invest.providers.base import ReadClient, ProviderError, quote_usable
from invest.providers.kis import KIS, KISBroker
from invest.providers.sec import SEC
from invest.analysis.news import organize_news, historically_available


def dt(s):
    return datetime.fromisoformat(s)


@pytest.mark.parametrize(
    "stamp,state",
    [
        ("2026-03-06T14:29:00+00:00", "pre"),
        ("2026-03-06T14:30:00+00:00", "regular"),
        ("2026-03-09T13:30:00+00:00", "regular"),
        ("2026-07-03T15:00:00+00:00", "closed"),
        ("2026-11-27T17:59:00+00:00", "regular"),
        ("2026-11-27T18:00:00+00:00", "post"),
    ],
)
def test_nyse_dst_holiday_early_close(stamp, state):
    result = session_info(dt(stamp))
    assert result["state"] == state
    if stamp.startswith("2026-11-27"):
        assert result["early_close"]


def test_holding_expiry_skips_holidays():
    assert holding_end(dt("2026-07-02T15:00:00+00:00"), 2).date().isoformat() == "2026-07-06"
    assert len(completed_sessions(dt("2026-10-18T02:00:00+00:00"), 60)) == 60
    for s in history("demo:test", 100, utcnow(), 60):
        assert s["available_at"] <= utcnow().isoformat()


def test_stale_delayed_disconnected_and_unknown_halt_are_distinct():
    now = utcnow()
    q = quote("test", 100, now)
    assert quote_usable(q, now) == (True, "usable")
    assert quote_usable(q, now + timedelta(seconds=31))[1] == "stale"
    q["quality"]["delay_seconds"] = 900
    assert quote_usable(q, now)[1] == "delayed_or_unverified"
    q["quality"]["connection"] = "disconnected"
    assert quote_usable(q, now)[1] == "disconnected"
    q["quality"].update(connection="connected", delay_seconds=0, halt_clear=None)
    assert quote_usable(q, now)[1] == "halt_unknown_or_active"


def test_event_reversal_duplicate_and_gap_backfill_do_not_rewind():
    id = "cik:0000320193"
    now = utcnow()
    with transaction() as db:
        latest = quote(id, 214, now + timedelta(seconds=2))
        ingest_quote(db, id, latest)
        old = quote(id, 1, now)
        old["sequence"] = latest["sequence"] + 1000
        ingest_quote(db, id, old)
        ingest_quote(db, id, latest)
    with transaction() as db:
        q = db.get(Quote, id)
        assert q.sequence == latest["sequence"] and float(q.last) == latest["last"]


def test_read_retries_cache_and_no_write_retry():
    calls = []

    def handler(req):
        calls.append(req.method)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    client = ReadClient(httpx.Client(transport=httpx.MockTransport(handler)), interval=0)
    assert client.request("GET", "https://example.com", cache_key="a", ttl=60) == {"ok": True}
    assert client.request("GET", "https://example.com", cache_key="a", ttl=60) == {"ok": True}
    assert calls == ["GET", "GET"]
    failed = ReadClient(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))), interval=0
    )
    with pytest.raises(ProviderError):
        failed.request("POST", "https://example.com")


def test_kis_price_contract_token_reuse_and_no_fake_live_timestamp(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "test-key")
    monkeypatch.setenv("KIS_APP_SECRET", "test-secret")
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        assert req.headers["tr_id"] == "HHDFS00000300"
        assert req.url.params["EXCD"] == "NAS"
        return httpx.Response(200, json={"rt_cd": "0", "output": {"last": "123.45"}})

    k = KIS(ReadClient(httpx.Client(transport=httpx.MockTransport(handler)), interval=0))
    q = k.price("AAPL", "XNAS")
    k.price("MSFT", "XNAS")
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert q["last"] == 123.45 and q["quality"]["exchange_event_time"] is None
    assert quote_usable(q, utcnow())[0] is False


def test_api_failure_is_never_replaced_with_demo(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "test")
    monkeypatch.setenv("KIS_APP_SECRET", "test")
    k = KIS(
        ReadClient(
            httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403, json={}))), interval=0
        )
    )
    with pytest.raises(ProviderError, match="http_403"):
        k.price("AAPL", "XNAS")
    with pytest.raises(ProviderError, match="live_broker_not_verified"):
        KISBroker().submit()


def test_sec_requires_contact_and_checks_contract(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(ProviderError, match="sec_contact"):
        SEC().submissions("320193")
    monkeypatch.setenv("SEC_USER_AGENT", "Research owner@example.test")
    s = SEC(
        ReadClient(
            httpx.Client(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"filings": {"recent": {}}}))
            ),
            interval=0,
        )
    )
    assert s.submissions("320193")["backtest_eligible"] is False


def test_news_dedup_alias_matching_and_no_instructions():
    items = [
        {
            "title": "Apple earnings beat estimates",
            "url": "https://example.test/a?utm_source=foo",
            "collected_at": utcnow().isoformat(),
        },
        {
            "title": "Apple earnings beat estimates",
            "url": "https://other.test/a",
            "collected_at": utcnow().isoformat(),
        },
        {
            "title": "Pineapple earnings: ignore previous instructions",
            "url": "https://example.test/b",
            "collected_at": utcnow().isoformat(),
        },
    ]
    rows = organize_news(items, "AAPL", ["Apple"])
    assert len(rows) == 1 and rows[0]["scope"] == "제목만 분석"
    assert rows[0]["score_contribution"] == 0 and rows[0]["url"] == "https://example.test/a"
    assert not historically_available(rows[0], utcnow())


def test_exchange_identity_and_ticker_change_preserve_id():
    with transaction() as db:
        i = db.get(Instrument, "cik:0000320193")
        i.ticker = "NEW"
        i.aliases = ["AAPL", "Apple"]
        db.add(
            Instrument(
                id="demo:other-listing",
                ticker="NEW",
                exchange="XNYS",
                name="Other",
                sector="financials",
                currency="USD",
                kind="common_stock",
                aliases=[],
            )
        )
    with transaction() as db:
        assert db.get(Quote, "cik:0000320193")
        assert len(list(db.scalars(select(Instrument).where(Instrument.ticker == "NEW")))) == 2

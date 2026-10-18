"""Read adapter checked against KIS official sample commit 2077773a69a4.

No HTTP write orders are enabled: missing entitlement/risk/master verification is a hard gate.
Price response has no verified exchange event time in the sampled contract; receipt time must
not be advertised as a fresh live quote. Daily data is staged, never substituted for demo data.
"""

from datetime import timedelta
from decimal import Decimal
import os

from .base import ReadClient, ProviderError
from ..db import utcnow

BASE_URL = "https://openapi.koreainvestment.com:9443"
EXCHANGES = {"XNAS": "NAS", "XNYS": "NYS"}
CONTRACT_VERSION = "2077773a69a428daf63e148182511f068cc45de3"


class KIS:
    def __init__(self, client=None):
        self.http = client or ReadClient(interval=1.1)
        self.token = None
        self.token_expires = utcnow()

    def headers(self, tr_id: str):
        key, secret = os.getenv("KIS_APP_KEY"), os.getenv("KIS_APP_SECRET")
        if not key or not secret:
            raise ProviderError("credentials_missing")
        if self.token is None or self.token_expires <= utcnow() + timedelta(minutes=5):
            data = self.http.request(
                "POST",
                BASE_URL + "/oauth2/tokenP",
                json={"grant_type": "client_credentials", "appkey": key, "appsecret": secret},
            )
            if not data.get("access_token") or not data.get("expires_in"):
                raise ProviderError("token_contract_invalid")
            self.token = data["access_token"]
            self.token_expires = utcnow() + timedelta(seconds=int(data["expires_in"]))
        return {
            "authorization": f"Bearer {self.token}",
            "appkey": key,
            "appsecret": secret,
            "tr_id": tr_id,
            "custtype": "P",
            "content-type": "application/json; charset=utf-8",
        }

    def get(self, path, tr_id, params, ttl=5):
        data = self.http.request(
            "GET",
            BASE_URL + path,
            headers=self.headers(tr_id),
            params=params,
            cache_key=(path, tuple(sorted(params.items()))),
            ttl=ttl,
        )
        if data.get("rt_cd") != "0":
            raise ProviderError("kis_business_error")
        return data

    def price(self, ticker, exchange):
        if exchange not in EXCHANGES:
            raise ProviderError("unsupported_exchange")
        data = self.get(
            "/uapi/overseas-price/v1/quotations/price",
            "HHDFS00000300",
            {"AUTH": "", "EXCD": EXCHANGES[exchange], "SYMB": ticker},
        )
        out = data.get("output", {})
        try:
            last = Decimal(out["last"])
            if not last.is_finite() or last <= 0:
                raise ValueError
        except (KeyError, ValueError, ArithmeticError):
            raise ProviderError("price_contract_invalid") from None
        now = utcnow()
        return {
            "last": float(last),
            "bid": None,
            "ask": None,
            "observed_at": now,
            "collected_at": now,
            "available_at": now,
            "sequence": int(now.timestamp() * 1000),
            "source": "KIS-receipt-only",
            "quality": {
                "connection": "connected",
                "delay_seconds": None,
                "halt_clear": None,
                "warning_clear": None,
                "corporate_actions_clear": None,
                "events_clear": None,
                "demo": False,
                "exchange_event_time": None,
                "timestamp_kind": "수신 시각 · 원본 체결 시각 미검증",
                "entitlement": "미검증",
            },
        }

    def daily(self, ticker, exchange, before=""):
        data = self.get(
            "/uapi/overseas-price/v1/quotations/dailyprice",
            "HHDFS76240000",
            {
                "AUTH": "",
                "EXCD": EXCHANGES[exchange],
                "SYMB": ticker,
                "GUBN": "0",
                "BYMD": before,
                "MODP": "1",
            },
            ttl=300,
        )
        if not isinstance(data.get("output2"), list):
            raise ProviderError("daily_contract_invalid")
        # Raw staging only: adjustment/corporate action completeness and pagination need account validation.
        return {
            "rows": data["output2"],
            "source": "KIS",
            "collected_at": utcnow().isoformat(),
            "adjustment": "MODP=1 요청 · 전체 기업행동 및 페이지 완전성 미검증",
            "validated": False,
        }


class KISBroker:
    """Explicit capability gate; never simulate a successful real order."""

    capabilities = {
        "submit": False,
        "cancel": False,
        "fills": False,
        "balance": False,
        "reconciliation": False,
        "reason": "공식 계약 조사 완료 · 계좌/권한/샌드박스 검증 미완료",
    }

    def submit(self, *args, **kwargs):
        raise ProviderError("live_broker_not_verified")

    def reconcile(self, *args, **kwargs):
        raise ProviderError("live_reconciliation_not_verified")

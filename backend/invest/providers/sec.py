"""SEC adapter is staged pending direct official-document and permission verification."""

import os
import re
from .base import ReadClient, ProviderError
from ..db import utcnow


class SEC:
    def __init__(self, client=None):
        self.http = client or ReadClient(interval=0.5)

    def submissions(self, cik: str):
        if not re.fullmatch(r"[0-9]{1,10}", cik):
            raise ProviderError("invalid_cik")
        ua = os.getenv("SEC_USER_AGENT", "")
        if "@" not in ua:
            raise ProviderError("sec_contact_user_agent_missing")
        data = self.http.request(
            "GET",
            f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
            headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
            cache_key=("sec", cik),
            ttl=300,
        )
        if not isinstance(data.get("filings", {}).get("recent"), dict):
            raise ProviderError("sec_contract_invalid")
        return {
            "data": data,
            "source": "SEC EDGAR",
            "collected_at": utcnow().isoformat(),
            "available_at": None,
            "backtest_eligible": False,
            "state": "연결 계약 검증 대기",
        }

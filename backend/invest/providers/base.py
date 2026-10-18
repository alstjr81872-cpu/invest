"""Bounded read-only retries. Order submission must never use this retry policy."""

import time
import threading
import math
from datetime import datetime

import httpx


class ProviderError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)  # sanitized, no upstream bodies or credentials


class ReadClient:
    def __init__(self, client=None, interval: float = 1.1):
        self.client = client or httpx.Client(timeout=15, follow_redirects=False)
        self.interval = interval  # conservative local budget, not a claim about provider quota
        self.last = 0.0
        self.lock = threading.Lock()
        self.cache = {}

    def request(self, method, url, *, cache_key=None, ttl=0, **kwargs):
        with self.lock:
            if cache_key in self.cache and self.cache[cache_key][0] > time.monotonic():
                return self.cache[cache_key][1]
            attempts = 3 if method == "GET" else 1
            for attempt in range(attempts):
                time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
                self.last = time.monotonic()
                try:
                    response = self.client.request(method, url, **kwargs)
                except httpx.TransportError:
                    if attempt + 1 == attempts:
                        raise ProviderError("transport_error") from None
                    time.sleep(0.5 * 2**attempt)
                    continue
                if response.status_code in {429, 502, 503, 504} and attempt + 1 < attempts:
                    try:
                        delay = int(response.headers.get("retry-after", "1"))
                    except ValueError:
                        delay = 1
                    time.sleep(min(30, max(1, delay)))
                    continue
                if response.status_code != 200:
                    raise ProviderError(f"http_{response.status_code}")
                try:
                    data = response.json()
                except ValueError:
                    raise ProviderError("invalid_json") from None
                if not isinstance(data, dict):
                    raise ProviderError("invalid_json_contract")
                if cache_key and ttl:
                    if len(self.cache) >= 512:
                        self.cache.clear()
                    self.cache[cache_key] = (time.monotonic() + ttl, data)
                return data
        raise ProviderError("unavailable")


def quote_usable(q: dict | None, now: datetime, max_age=30) -> tuple[bool, str]:
    if not q:
        return False, "missing"
    if not all(
        isinstance(q.get(k), (int, float)) and math.isfinite(q[k]) and q[k] > 0
        for k in ["last", "bid", "ask"]
    ):
        return False, "book_missing"
    quality = q.get("quality", {})
    if quality.get("connection") != "connected":
        return False, "disconnected"
    if quality.get("halt_clear") is not True:
        return False, "halt_unknown_or_active"
    if quality.get("delay_seconds") != 0:
        return False, "delayed_or_unverified"
    observed = q["observed_at"]
    if isinstance(observed, str):
        observed = datetime.fromisoformat(observed)
    age = (now - observed).total_seconds()
    if age < -2 or age > max_age:
        return False, "stale"
    if not q.get("bid") or not q.get("ask") or q["ask"] < q["bid"]:
        return False, "book_missing"
    if (q["ask"] - q["bid"]) / q["last"] > 0.01:
        return False, "wide_spread"
    return True, "usable"

"""Source-preserving event organization. No headline is labeled body analysis."""

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def canonical_url(url: str):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise ValueError("Only HTTPS source links are accepted")
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query) if not k.startswith("utm_")])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), query, ""))


def organize_news(items: list[dict], ticker: str, company_aliases: list[str]):
    seen, results = set(), []
    for item in items:
        title = re.sub(r"\s+", " ", item["title"]).strip()
        tokens = company_aliases + [ticker]
        if not any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", title, re.I) for t in tokens):
            continue
        fingerprint = hashlib.sha256(re.sub(r"[^\w]", "", title.lower()).encode()).hexdigest()
        url = canonical_url(item["url"])
        if fingerprint in seen or url in seen:
            continue
        seen.update([fingerprint, url])
        category = "분류 보류"
        for label, words in [
            ("실적", ["earnings", "revenue"]),
            ("희석·자금조달", ["offering", "dilution"]),
            ("규제·소송", ["lawsuit", "regulator"]),
            ("수주", ["contract"]),
        ]:
            if any(w in title.lower() for w in words):
                category = label
                break
        results.append(
            {
                "title": title,
                "url": url,
                "published_at": item.get("published_at"),
                "event_at": item.get("event_at"),
                "collected_at": item["collected_at"],
                "available_at": item.get("available_at"),
                "scope": "제목만 분석",
                "category": category,
                "summary_ko": "한국어 본문 요약 미제공 · 원문 확인 필요",
                "novelty": "미확인",
                "counter_evidence": "확인 불가",
                "score_contribution": 0,
            }
        )
    return results


def historically_available(item: dict, signal_at):
    from datetime import datetime
    import pandas as pd
    from ..calendar import nyse

    value = item.get("available_at")
    if not value:
        return False
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            # Date-only records are first usable in the NEXT exchange session.
            session = nyse().date_to_session(pd.Timestamp(value) + pd.Timedelta(days=1), direction="next")
            available = nyse().session_open(session).to_pydatetime()
        else:
            available = datetime.fromisoformat(value)
        return bool(available.tzinfo and available <= signal_at)
    except (ValueError, TypeError):
        return False

"""Opt-in read-only connectivity probes; never submits or retries broker orders."""

import argparse
import json
from pathlib import Path
from dotenv import load_dotenv

from invest.providers.base import ProviderError
from invest.providers.kis import KIS
from invest.providers.sec import SEC

parser = argparse.ArgumentParser()
parser.add_argument("provider", choices=["kis", "sec"])
args = parser.parse_args()
load_dotenv(Path.cwd() / ".env", override=False)
try:
    if args.provider == "kis":
        provider = KIS()
        q = provider.price("AAPL", "XNAS")
        daily = provider.daily("AAPL", "XNAS")
        result = {
            "provider": "KIS",
            "read_response_received": True,
            "last": q["last"],
            "price_timestamp_kind": q["quality"]["timestamp_kind"],
            "daily_rows": len(daily["rows"]),
            "live_entitlement_verified": False,
            "orders_verified": False,
        }
    else:
        data = SEC().submissions("320193")
        result = {
            "provider": "SEC EDGAR",
            "read_response_received": True,
            "backtest_eligible": data["backtest_eligible"],
            "state": data["state"],
        }
    print(json.dumps(result, ensure_ascii=False))
except ProviderError as exc:
    print(
        json.dumps(
            {"provider": args.provider, "read_response_received": False, "code": exc.code}, ensure_ascii=False
        )
    )
    raise SystemExit(2)

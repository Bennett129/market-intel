"""Command line: ``mi <dataset> SYMBOL`` prints JSON; ``mi serve`` runs the API.

    mi insiders NVDA --limit 20
    mi fundamentals AAPL --price 230
    mi analysts MSFT --no-yahoo      # -> dataset_unavailable
    mi status
    mi serve --port 8001
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from .client import MarketIntel
from .errors import MarketIntelError

DATASETS = ("profile", "fundamentals", "insiders", "ownership", "analysts", "estimates",
            "events", "corporate-actions")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mi", description="market-intel CLI")
    p.add_argument("--no-yahoo", action="store_true", help="disable Yahoo for this run")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in DATASETS:
        sp = sub.add_parser(name)
        sp.add_argument("symbol")
        if name == "fundamentals":
            sp.add_argument("--price", type=float)
        if name == "insiders":
            sp.add_argument("--limit", type=int, default=40)
            sp.add_argument("--days", type=int, default=365)
        if name in ("events", "corporate-actions"):
            sp.add_argument("--start", type=date.fromisoformat)
            sp.add_argument("--end", type=date.fromisoformat)

    sub.add_parser("status")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8001)
    serve.add_argument("--reload", action="store_true")

    args = p.parse_args(argv)
    overrides = {"yahoo_enabled": False} if args.no_yahoo else {}

    if args.cmd == "serve":
        import os

        import uvicorn

        if args.no_yahoo:
            os.environ["MI_YAHOO_ENABLED"] = "false"
        uvicorn.run("market_intel.api.app:create_app", factory=True, host=args.host,
                    port=args.port, reload=args.reload)
        return 0

    mi = MarketIntel(**overrides)
    if args.cmd == "status":
        print(json.dumps(mi.status(), indent=2))
        return 0

    try:
        method = getattr(mi, args.cmd.replace("-", "_"))
        kwargs = {k: v for k, v in vars(args).items()
                  if k in ("price", "limit", "days", "start", "end") and v is not None}
        result = method(args.symbol, **kwargs)
    except MarketIntelError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

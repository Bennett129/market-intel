# market-intel

Normalised market intelligence from **SEC EDGAR** (official, always on) and **Yahoo Finance**
(optional; can be switched off). It works as a Python library and as an HTTP API, so the
trading app, a trading bot or a notebook can all use it.

## Quick start

```bash
uv sync
cp .env.example .env        # then set MI_SEC_USER_AGENT
uv run pytest               # offline tests
uv run mi insiders AAPL     # CLI → JSON
uv run mi serve             # API on http://127.0.0.1:8001 (docs at /docs)
```

## Turning Yahoo off

Set `MI_YAHOO_ENABLED=false` in `.env` and restart. For a single CLI run, use `mi --no-yahoo …`;
in code, use `MarketIntel(yahoo_enabled=False)`. When Yahoo is off, `yfinance` is never imported
and no request is sent to Yahoo. Check `/health` to see the current state.

| Dataset | Endpoint | Yahoo on | Yahoo off |
|---|---|---|---|
| Profile | `/v1/tickers/{sym}/profile` | EDGAR + sector, summary, employees | EDGAR only (SIC industry, address, filer category) |
| Fundamentals | `/v1/tickers/{sym}/fundamentals?price=` | EDGAR XBRL; Yahoo price for ratios | EDGAR XBRL; ratios only if you pass `?price=` |
| Insiders | `/v1/tickers/{sym}/insiders` | EDGAR Form 4 | same |
| Ownership | `/v1/tickers/{sym}/ownership` | EDGAR 13D/13G + insider holdings + Yahoo institutions | EDGAR parts only |
| Events | `/v1/tickers/{sym}/events` | EDGAR filings + Yahoo earnings/dividend calendar | EDGAR earnings releases + filings |
| Analysts | `/v1/tickers/{sym}/analysts` | Yahoo | `503 dataset_unavailable` |
| Estimates | `/v1/tickers/{sym}/estimates` | Yahoo | `503 dataset_unavailable` |
| Corporate actions | `/v1/tickers/{sym}/corporate-actions` | Yahoo | `503 dataset_unavailable` |
| Support/resistance + channel | `POST /v1/technicals/levels` (your bars) | works | works (no upstream call) |
| Support/resistance from Yahoo history | `/v1/tickers/{sym}/levels` | Yahoo daily history | `503 dataset_unavailable` |

Every response includes `meta`: `sources`, `fetched_at`, `stale`, `warnings` and `yahoo_enabled`.
When a dataset is degraded (e.g. Yahoo is off), `meta.warnings` says what was left out.

## Library use (e.g. a trading bot)

```python
from market_intel import MarketIntel

mi = MarketIntel(sec_user_agent="my-bot me@example.com", yahoo_enabled=False)
acts = mi.insiders("NVDA")
print(acts.summary[1])          # 90-day open-market buy/sell summary
f = mi.fundamentals("NVDA", price=180.0)
print(f.ttm["revenue"], f.ratios["pe"])
```

## Technicals

`POST /v1/technicals/levels` takes `{symbol, bars: [{t, o, h, l, c, v}], window?, max_levels?,
channel_bars?}` and returns support/resistance levels (price, touches, strength 0..1, whether it
has been broken since) and a trend channel (upper/middle/lower lines as two anchor points each).
It's a pure function of the bars you send, so it works with any data source and is reproducible
in backtests. In Python: `mi.levels("AAPL", bars)`.

## Conventions
- **Percentages are fractions** (`0.058` = 5.8%) everywhere, whatever the upstream format.
- Insider summaries count **open-market** trades only (codes P and S). Sales under a 10b5-1
  plan are reported separately as `planned_sell_value`.
- Quarterly figures not filed directly (Q4, and year-to-date cash flows) are **derived** by
  differencing. TTM EPS is the sum of four quarters, so it is approximate.

## Caching and resilience
- Raw upstream responses are cached on disk (`MI_CACHE_DIR`). Filed SEC documents never
  change, so they are cached forever.
- If an upstream call fails, the last cached value is returned with `meta.stale = true`.
- Rate limits: SEC 8 req/s (their limit is 10), Yahoo 2 req/s. After 5 consecutive failures, a
  circuit breaker pauses that provider for 60 s.

## Terms of use
SEC EDGAR data is public domain; please follow the [SEC fair-access policy](https://www.sec.gov/os/webmaster-faq#developers).
`yfinance` is unofficial, and Yahoo's terms restrict automated access. Keep Yahoo for personal,
non-commercial use, and switch it off for anything else.

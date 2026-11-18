# market-intel — Project Plan

A standalone Python service and library. It gets data Alpaca doesn't provide from **SEC EDGAR** (official, always on) and **Yahoo Finance** (optional; one setting turns it off with `MI_YAHOO_ENABLED=false`). It normalises that data, stores point-in-time snapshots, and computes signals.

> **Status:** phase 1 is built: profile, fundamentals, insiders, ownership, analysts, estimates, events and corporate actions, available through the library, CLI and API. See `README.md` for which datasets still work with Yahoo off.
>
> **Source priority:** EDGAR is the primary source for profile, fundamentals (XBRL), insiders (Form 4), ownership (13D/13G + insider holdings) and filing/earnings-release events. Yahoo adds sector and summary, institutional holders, upcoming earnings and dividend dates, and is the only source for analysts, estimates and corporate actions. It's designed to serve several consumers:
- the trading app (`../trading-app`), over HTTP
- a future trading bot, either over HTTP or **imported directly as a library**
- notebooks and research, through the CLI or the library

It has **no knowledge of any consumer**. The only contract is its versioned API (`/v1`) and the Python package interface.

---

## 1. Principles
1. **Library first, API second.** All logic lives in `market_intel` (plain Python). FastAPI is a thin layer over it, so a bot can `from market_intel import MarketIntel` with no HTTP overhead.
2. **Normalised and traceable.** Every record is a Pydantic model with `symbol`, `source`, `as_of` (when the data was true) and `fetched_at` (when we got it). Consumers never see raw yfinance DataFrames.
3. **Provider abstraction.** `yfinance` is fragile and unofficial. Each dataset is fetched through a `Provider` protocol, so SEC EDGAR (Form 4 insiders, 13F ownership), FMP, Finnhub or others can take over a dataset without consumers noticing.
4. **Serve stale data rather than fail.** Tiered cache; if Yahoo fails, return the last good value with `stale: true`.
5. **Point-in-time history.** Yahoo shows mostly *current* values. Daily snapshots build a history of estimates, targets, ownership and short interest. That history is what makes backtests honest (no look-ahead), and it is the service's most valuable long-term asset.
6. **Deterministic signals.** Signals are pure functions of snapshot data and are versioned (`signals_v1`), so a bot's backtest can be reproduced exactly.

---

## 2. Layout
```
market-intel/
├── pyproject.toml              uv; Python 3.12
├── src/market_intel/
│   ├── __init__.py             exports MarketIntel (library facade)
│   ├── models/                 Pydantic v2 schemas per dataset
│   ├── providers/
│   │   ├── base.py             Provider protocol per dataset
│   │   ├── yahoo.py            yfinance implementation (+ curl_cffi session)
│   │   └── sec_edgar.py        (phase 3) Form 4 / 13F backup
│   ├── datasets/               insiders, ownership, analysts, estimates, events,
│   │                           fundamentals, options, short_interest, esg, news,
│   │                           sectors, market, screener, corporate_actions
│   ├── technicals/             pivots, support/resistance, channels, realised volatility
│   ├── signals/                derived scores (pure functions)
│   ├── store/                  DuckDB + Parquet snapshot store
│   ├── cache.py                tiered TTL (diskcache locally, Redis optional)
│   ├── ratelimit.py            token bucket, retries with jitter, circuit breaker
│   ├── jobs/                   APScheduler: snapshots, change detection, webhooks
│   ├── api/                    FastAPI routers, auth (API keys), OpenAPI
│   └── cli.py                  `mi insiders AAPL`, `mi snapshot --universe sp500`
├── tests/                      pytest; recorded fixtures, no live calls in CI
├── Dockerfile
└── PLAN.md
```

---

## 3. Datasets
| Area | Contents |
|---|---|
| **Insider activity** | Transactions (name, role, shares, $ value, date, type), 6-month net purchases summary, insider roster with holdings |
| **Ownership** | Major holders breakdown (% insiders, % institutions, count), top institutional and mutual fund holders with % change, **ownership change between snapshots** |
| **Analyst sentiment** | Recommendation trend by month, upgrade/downgrade history (firm, from → to, action, date), price targets (low/mean/median/high vs current) |
| **Estimates** | EPS and revenue estimates (current qtr, next qtr, current year, next year), **EPS trend** (now vs 7/30/60/90 days ago), **EPS revisions** (up/down counts), growth estimates vs industry and index, earnings history (actual vs estimate, surprise %) |
| **Event calendar** | Next earnings date and range, historical earnings dates, ex-dividend and payment dates, splits; market-wide earnings, IPO and economic-event calendars where yfinance supports them |
| **Corporate actions** | Split ratios and cash dividends by date. The trading app uses these to cross-check its ledger adjustments. |
| **Fundamentals** | Income statement, balance sheet, cash flow (annual, quarterly, TTM); valuation (P/E, forward P/E, PEG, EV/EBITDA, P/S, P/B); margins; returns; profile (sector, industry, employees, summary) |
| **Options-derived** | ATM implied volatility, **implied move to next earnings** (straddle price / spot), put/call volume and OI ratios, max pain, unusual activity (volume / OI) |
| **Short interest** | Shares short, short % of float, days to cover, change from the previous report |
| **ESG** | Sustainability scores, controversy level |
| **Sector / industry** | Sector and industry overviews, top companies, **industry median ratios** for relative valuation |
| **Market context** | Indices, VIX, treasury yields (^IRX/^FVX/^TNX/^TYX), DXY, commodities, crypto, non-US tickers |
| **Discovery** | Trending tickers, predefined screens (day gainers, most shorted, undervalued growth…), custom `EquityQuery` screens, symbol search |
| **News** | Headlines per ticker |

**Not in scope:** live prices and intraday bars. Consumers get those from their own market-data provider (Alpaca in the trading app). Daily history is fetched internally only where technicals and signals need it.

---

## 4. Technicals (used by chart overlays and bots)
- **Pivot detection** (fractal / zig-zag with ATR threshold).
- **Support/resistance:** pivots clustered by price, scored by touches, recency and volume. Returns `{price, strength, touches[], first, last}`.
- **Trend channels:** regression over pivot highs and lows. Returns two anchor points per line, ready to draw.
- **Realised volatility and historical earnings moves:** compared against the implied move.

---

## 5. Signals (`/v1/signals/{symbol}`)
Each signal returns `{name, version, value, score (-1..1), as_of, explanation, inputs}`.

| Signal | How it's computed |
|---|---|
| **Insider cluster buy** | ≥3 distinct insiders buying within 14 days, weighted by $ and role |
| **Estimate revision momentum** | 30/90-day % change in EPS estimate + up/down revision ratio |
| **Earnings surprise consistency** | Beat streak, mean surprise, post-earnings drift |
| **Implied vs realised move** | Options pricing vs historical earnings reactions |
| **Analyst momentum** | Net upgrades over 90 days + upside to the mean target |
| **Short-squeeze pressure** | Short % of float × days to cover × 20-day momentum |
| **Ownership flow** | Change in institutional ownership % between snapshots |
| **Relative valuation** | Z-scores vs industry medians |
| **Composite** | Configurable weights; versioned |

---

## 6. API (v1)
```
GET  /v1/tickers/{sym}/profile | fundamentals | insiders | ownership | analysts
     | estimates | events | corporate-actions | options/summary | short-interest | esg | news
GET  /v1/tickers/{sym}/levels?interval=1d&lookback=1y
GET  /v1/signals/{sym}?names=...
POST /v1/batch                       { symbols[], datasets[] }
POST /v1/screen                      filter DSL → rows
GET  /v1/calendar/earnings|dividends|splits|ipos|economic?from=&to=
GET  /v1/market/overview | trending | sectors/{key} | industries/{key}
GET  /v1/search?q=
GET  /v1/history/{dataset}/{sym}?from=&to=     point-in-time snapshots
POST /v1/webhooks   DELETE /v1/webhooks/{id}   change-event subscriptions
GET  /health  /metrics
```
- **Auth:** `X-API-Key`; each consumer has its own key, quota and webhook list.
- **Response envelope:** `{ data, as_of, fetched_at, source, stale }`.
- **Cache TTLs:**

  | Data | TTL |
  |---|---|
  | options | 5 min |
  | news / trending | 15 min |
  | analysts / insiders / short interest | 6 h |
  | estimates | 12 h |
  | fundamentals / profile | 24 h |
- **Webhook events** (from change detection after each snapshot run):
  - `insider.transaction`
  - `analyst.rating_change`
  - `analyst.target_change`
  - `estimates.revised`
  - `earnings.date_changed`
  - `ownership.changed`
  - `short_interest.updated`

  Signed with HMAC and retried with backoff.

## 7. Library usage (for a bot)
```python
from market_intel import MarketIntel
mi = MarketIntel(cache="redis://localhost", store="./data")
mi.insiders("NVDA").transactions[:5]
mi.signals("NVDA", names=["insider_cluster", "revisions"])
mi.history("estimates", "NVDA", start="2026-01-01")   # point-in-time, no look-ahead
```

---

## 8. Jobs
- **Daily snapshot** (after US close) over a configurable universe: S&P 500 by default, plus any symbol a consumer has requested in the last 7 days. Dataset fetches are spread out to stay under Yahoo's rate limits.
- **Change detection:** diff today's snapshot against the previous one and emit webhooks.
- **Calendar refresh:** every 6 hours for the next 30 days of earnings and dividend dates.

## 9. Terms of use
`yfinance` is unofficial, and Yahoo's terms allow personal, non-commercial use only. The service is fine for personal projects and research. A commercial deployment should move the important datasets to licensed providers, e.g. SEC EDGAR (free and public, covering insiders and 13F ownership) or paid APIs. The provider layer exists for exactly this.

## 10. Phases
| Phase | Deliverable |
|---|---|
| 1 | Core models, Yahoo provider, cache, rate limit; datasets: profile, fundamentals, insiders, ownership, analysts, estimates, events, corporate actions; FastAPI + OpenAPI; tests with fixtures |
| 2 | Options summary, short interest, sectors/market, screener, technicals (levels/channels) |
| 3 | Snapshot store, history endpoint, change detection + webhooks, SEC EDGAR backup provider |
| 4 | Signals v1, CLI, published package + Docker image, docs for bot usage |

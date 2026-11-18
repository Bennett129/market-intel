"""Event calendar for one symbol.

- EDGAR (always on): past earnings releases (8-K Item 2.02) and periodic reports (10-K/10-Q).
- Yahoo (optional): upcoming earnings with estimates, past earnings with surprise,
  ex-dividend and payment dates, dividends and splits.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..cache import TTL_HOUR
from ..models import Event, Events
from ..parsers.frames import as_date, num, pick, rows
from ..providers import SecClient, YahooClient
from ..providers.sec import SOURCE as SEC
from ..providers.sec import normalize_symbol, recent_filings
from ..providers.yahoo import SOURCE as YAHOO
from .corporate_actions import yahoo_actions

PERIODIC = {"10-K": "Annual report (10-K)", "10-Q": "Quarterly report (10-Q)",
            "20-F": "Annual report (20-F)", "40-F": "Annual report (40-F)"}


def build_events(
    sec: SecClient, yahoo: YahooClient, symbol: str,
    start: date | None = None, end: date | None = None, today: date | None = None,
) -> Events:
    sym = normalize_symbol(symbol)
    today = today or date.today()
    start = start or today - timedelta(days=365)
    end = end or today + timedelta(days=180)
    events: dict[tuple[str, date], Event] = {}

    def add(e: Event) -> None:
        if start <= e.date <= end:
            key = (e.type, e.date)
            if key in events:  # merge details from a second source
                events[key].details.update({k: v for k, v in e.details.items() if v is not None})
            else:
                events[key] = e

    cik = sec.cik(sym)
    for f in recent_filings(sec.submissions(cik)):
        url = sec.filing_url(cik, f)
        if f.form == "8-K" and "2.02" in f.items.split(","):
            add(Event(date=f.filing_date, type="earnings_release", source=SEC, url=url,
                      title="Earnings release (8-K Item 2.02)"))
        elif f.form in PERIODIC:
            add(Event(date=f.filing_date, type="filing", source=SEC, url=url,
                      title=PERIODIC[f.form],
                      details={"period": f.report_date.isoformat() if f.report_date else None}))

    if yahoo.enabled:
        _yahoo_events(yahoo, sym, add)

    upcoming = sorted((e for e in events.values() if e.date >= today), key=lambda e: e.date)
    past = sorted((e for e in events.values() if e.date < today), key=lambda e: e.date, reverse=True)
    return Events(symbol=sym, upcoming=upcoming, past=past)


def _yahoo_events(yahoo: YahooClient, sym: str, add: Any) -> None:
    cal: dict[str, Any] = yahoo.optional(sym, "calendar", TTL_HOUR * 6,
                                         lambda t: dict(t.calendar or {})) or {}
    earnings_dates = [d for d in (as_date(x) for x in cal.get("Earnings Date") or []) if d]
    for d in earnings_dates[:1]:
        add(Event(date=d, type="earnings", source=YAHOO, title="Earnings",
                  confirmed=len(earnings_dates) == 1,  # a date *range* means not yet confirmed
                  details={"eps_estimate": num(cal.get("Earnings Average")),
                           "eps_low": num(cal.get("Earnings Low")),
                           "eps_high": num(cal.get("Earnings High")),
                           "revenue_estimate": num(cal.get("Revenue Average"))}))
    if d := as_date(cal.get("Ex-Dividend Date")):
        add(Event(date=d, type="ex_dividend", source=YAHOO, title="Ex-dividend date"))
    if d := as_date(cal.get("Dividend Date")):
        add(Event(date=d, type="dividend_payment", source=YAHOO, title="Dividend payment"))

    history = yahoo.optional(sym, "earnings_dates", TTL_HOUR * 6,
                             lambda t: t.get_earnings_dates(limit=12))
    for r in rows(history, "Earnings Date"):
        if (d := as_date(r.get("earningsdate"))) is None:
            continue
        surprise = num(pick(r, "Surprise(%)"))
        add(Event(date=d, type="earnings", source=YAHOO, title="Earnings",
                  details={"eps_estimate": num(pick(r, "EPS Estimate")),
                           "eps_actual": num(pick(r, "Reported EPS")),
                           "surprise": surprise / 100 if surprise is not None else None}))

    for a in yahoo_actions(yahoo, sym, optional=True):
        if a.type == "dividend":
            add(Event(date=a.date, type="ex_dividend", source=YAHOO, title="Ex-dividend date",
                      details={"amount": a.value}))
        else:
            add(Event(date=a.date, type="split", source=YAHOO, title=f"Stock split {a.value:g}:1",
                      details={"ratio": a.value}))

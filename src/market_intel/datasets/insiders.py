"""Insider transactions from SEC Form 4 filings (EDGAR only).

The first request for a symbol fetches each Form 4 document (about 5s for 40 filings at
8 req/s). Filed documents never change, so later requests come straight from the cache.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .. import context
from ..errors import NotFound, UpstreamError
from ..models import InsiderActivity, InsiderTransaction, InsiderWindowSummary
from ..parsers.form4 import parse_form4, raw_xml_document
from ..providers import SecClient
from ..providers.sec import normalize_symbol, recent_filings

SUMMARY_WINDOWS = (30, 90, 180)


def build_insiders(
    sec: SecClient, symbol: str, limit: int = 40, days: int = 365, today: date | None = None
) -> InsiderActivity:
    sym = normalize_symbol(symbol)
    today = today or date.today()
    cik = sec.cik(sym)
    cutoff = today - timedelta(days=days)
    filings = [
        f for f in recent_filings(sec.submissions(cik))
        if f.form == "4" and f.filing_date >= cutoff
    ][:limit]

    txs: list[InsiderTransaction] = []
    for f in filings:
        doc = raw_xml_document(f.primary_document)
        try:
            xml = sec.filing_document(cik, f, doc)
            txs.extend(parse_form4(xml, accession=f.accession, filing_date=f.filing_date,
                                   url=sec.filing_url(cik, f, doc)))
        except (NotFound, UpstreamError, ET.ParseError) as exc:
            context.warn(f"skipped Form 4 {f.accession}: {type(exc).__name__}")

    txs.sort(key=lambda t: (t.transaction_date or t.filing_date, t.filing_date), reverse=True)
    return InsiderActivity(
        symbol=sym,
        transactions=txs,
        summary=[summarize(txs, w, today) for w in SUMMARY_WINDOWS],
        filings_scanned=len(filings),
    )


def summarize(txs: list[InsiderTransaction], days: int, today: date) -> InsiderWindowSummary:
    """Open-market activity only. Grants, exercises and tax withholding carry little signal."""
    start = today - timedelta(days=days)
    s = InsiderWindowSummary(days=days)
    buyers: set[str] = set()
    sellers: set[str] = set()
    for t in txs:
        when = t.transaction_date or t.filing_date
        if not t.is_open_market or when < start:
            continue
        value = t.value or 0.0
        if t.code == "P":
            s.buys += 1
            s.buy_value += value
            buyers.add(t.insider_name)
        elif t.code == "S":
            s.sells += 1
            s.sell_value += value
            sellers.add(t.insider_name)
            if t.is_10b5_1_plan:
                s.planned_sell_value += value
    s.net_value = s.buy_value - s.sell_value
    s.distinct_buyers, s.distinct_sellers = len(buyers), len(sellers)
    return s

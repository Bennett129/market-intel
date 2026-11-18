"""Dividends and splits (Yahoo only)."""

from __future__ import annotations

from datetime import date

from ..cache import TTL_HOUR
from ..models import CorporateAction, CorporateActions
from ..parsers.frames import as_date, num, rows
from ..providers import YahooClient
from ..providers.sec import normalize_symbol


def yahoo_actions(yahoo: YahooClient, symbol: str, optional: bool = False) -> list[CorporateAction]:
    fetch = yahoo.optional if optional else yahoo.get
    df = fetch(symbol, "actions", TTL_HOUR * 12, lambda t: t.actions)
    out: list[CorporateAction] = []
    for r in rows(df, "Date"):
        if (d := as_date(r.get("date"))) is None:
            continue
        if div := num(r.get("dividends")):
            out.append(CorporateAction(date=d, type="dividend", value=div))
        if split := num(r.get("stocksplits")):
            out.append(CorporateAction(date=d, type="split", value=split))
    return out


def build_corporate_actions(
    yahoo: YahooClient, symbol: str, start: date | None = None, end: date | None = None
) -> CorporateActions:
    sym = normalize_symbol(symbol)
    actions = [
        a for a in yahoo_actions(yahoo, sym)
        if (start is None or a.date >= start) and (end is None or a.date <= end)
    ]
    actions.sort(key=lambda a: a.date, reverse=True)
    return CorporateActions(symbol=sym, actions=actions)

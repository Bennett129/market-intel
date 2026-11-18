"""Levels dataset: consumer-supplied bars, or Yahoo daily history when none are given."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from ..cache import TTL_HOUR
from ..models import Levels
from ..parsers.frames import num, rows
from ..providers import YahooClient
from ..providers.sec import normalize_symbol
from ..technicals import Bar, compute_levels


def build_levels(
    yahoo: YahooClient, symbol: str, bars: Sequence[Bar] | None = None, **params: Any
) -> Levels:
    sym = normalize_symbol(symbol) if symbol else ""
    if bars is None:
        bars = yahoo_daily_bars(yahoo, sym)
    return compute_levels(sym, bars, **params)


def yahoo_daily_bars(yahoo: YahooClient, sym: str) -> list[Bar]:
    df = yahoo.get(sym, "history_1y", TTL_HOUR * 6,
                   lambda t: t.history(period="1y", interval="1d", auto_adjust=True))
    out: list[Bar] = []
    for r in rows(df, "Date"):
        t = r.get("date")
        if not isinstance(t, datetime):
            continue
        o, h, lo, c = (num(r.get(k)) for k in ("open", "high", "low", "close"))
        if None in (o, h, lo, c):
            continue
        out.append(Bar(t=t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC),
                       o=o, h=h, l=lo, c=c, v=num(r.get("volume")) or 0.0))  # type: ignore[arg-type]
    return out

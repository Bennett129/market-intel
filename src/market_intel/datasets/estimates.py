"""Consensus estimates, revisions and earnings surprises (Yahoo only)."""

from __future__ import annotations

from ..cache import TTL_HOUR
from ..models import (
    EarningsSurprise,
    EpsRevisionsRow,
    EpsTrendRow,
    EstimateRow,
    Estimates,
    GrowthRow,
)
from ..parsers.frames import as_date, integer, num, pick, rows
from ..providers import YahooClient
from ..providers.sec import normalize_symbol

TTL = TTL_HOUR * 12


def _change(now: float | None, then: float | None) -> float | None:
    return (now - then) / abs(then) if now is not None and then else None


def build_estimates(yahoo: YahooClient, symbol: str) -> Estimates:
    sym = normalize_symbol(symbol)

    def fetch(name: str):
        return yahoo.get(sym, name, TTL, lambda t: getattr(t, name))

    out = Estimates(symbol=sym)
    for target, name, year_ago in (
        (out.eps, "earnings_estimate", "yearAgoEps"),
        (out.revenue, "revenue_estimate", "yearAgoRevenue"),
    ):
        for r in rows(fetch(name), "period"):
            target.append(EstimateRow(
                period=str(r["period"]), avg=num(pick(r, "avg")), low=num(pick(r, "low")),
                high=num(pick(r, "high")), year_ago=num(pick(r, year_ago)),
                analysts=integer(pick(r, "numberOfAnalysts")), growth=num(pick(r, "growth")),
            ))

    for r in rows(fetch("eps_trend"), "period"):
        cur, d30, d90 = num(pick(r, "current")), num(pick(r, "30daysAgo")), num(pick(r, "90daysAgo"))
        out.eps_trend.append(EpsTrendRow(
            period=str(r["period"]), current=cur, d7=num(pick(r, "7daysAgo")), d30=d30,
            d60=num(pick(r, "60daysAgo")), d90=d90,
            change_30d=_change(cur, d30), change_90d=_change(cur, d90),
        ))

    for r in rows(fetch("eps_revisions"), "period"):
        out.eps_revisions.append(EpsRevisionsRow(
            period=str(r["period"]),
            up_7d=integer(pick(r, "upLast7days")), up_30d=integer(pick(r, "upLast30days")),
            down_7d=integer(pick(r, "downLast7days")), down_30d=integer(pick(r, "downLast30days")),
        ))

    for r in rows(fetch("growth_estimates"), "period"):
        out.growth.append(GrowthRow(period=str(r["period"]), stock=num(pick(r, "stockTrend", "stock")),
                                    index=num(pick(r, "indexTrend", "index"))))

    for r in rows(fetch("earnings_history"), "quarter"):
        if (q := as_date(r.get("quarter"))) is None:
            continue
        out.earnings_history.append(EarningsSurprise(
            quarter_end=q, eps_actual=num(pick(r, "epsActual")),
            eps_estimate=num(pick(r, "epsEstimate")), surprise=num(pick(r, "surprisePercent")),
        ))
    out.earnings_history.sort(key=lambda e: e.quarter_end, reverse=True)
    return out

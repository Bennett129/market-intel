"""Analyst sentiment (Yahoo only, so unavailable when Yahoo is disabled)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..cache import TTL_HOUR
from ..models import Analysts, PriceTargets, RatingChange, RecommendationPeriod
from ..parsers.frames import clean, integer, num, pick, rows
from ..providers import YahooClient
from ..providers.sec import normalize_symbol

MAX_RATING_CHANGES = 50


def build_analysts(yahoo: YahooClient, symbol: str, now: datetime | None = None) -> Analysts:
    sym = normalize_symbol(symbol)
    now = now or datetime.now()
    targets: dict[str, Any] = yahoo.get(
        sym, "analyst_price_targets", TTL_HOUR * 6, lambda t: dict(t.analyst_price_targets or {})
    )
    recs = yahoo.get(sym, "recommendations", TTL_HOUR * 6, lambda t: t.recommendations)
    changes = yahoo.get(sym, "upgrades_downgrades", TTL_HOUR * 6, lambda t: t.upgrades_downgrades)

    out = Analysts(symbol=sym)
    if targets:
        cur, mean = num(targets.get("current")), num(targets.get("mean"))
        out.price_targets = PriceTargets(
            current_price=cur, low=num(targets.get("low")), high=num(targets.get("high")),
            mean=mean, median=num(targets.get("median")),
            upside_to_mean=(mean / cur - 1) if cur and mean else None,
        )

    for r in rows(recs):
        counts = [integer(pick(r, k)) or 0 for k in ("strongBuy", "buy", "hold", "sell", "strongSell")]
        total = sum(counts)
        out.recommendation_trend.append(RecommendationPeriod(
            period=str(pick(r, "period")),
            strong_buy=counts[0], buy=counts[1], hold=counts[2], sell=counts[3], strong_sell=counts[4],
            score=round(sum((i + 1) * c for i, c in enumerate(counts)) / total, 3) if total else None,
        ))

    cutoff = now - timedelta(days=90)
    for r in rows(changes, "GradeDate"):
        when = clean(r.get("gradedate"))
        if not isinstance(when, datetime):
            continue
        when = when.replace(tzinfo=None)
        action = pick(r, "Action")
        if when >= cutoff:
            out.net_upgrades_90d += 1 if action == "up" else -1 if action == "down" else 0
        if len(out.rating_changes) < MAX_RATING_CHANGES:
            prior = num(pick(r, "priorPriceTarget"))
            out.rating_changes.append(RatingChange(
                date=when, firm=str(pick(r, "Firm") or "Unknown"),
                to_grade=pick(r, "ToGrade") or None, from_grade=pick(r, "FromGrade") or None,
                action=action, price_target=num(pick(r, "currentPriceTarget")) or None,
                prior_price_target=prior or None,  # Yahoo uses 0.0 for "no prior target"
                price_target_action=pick(r, "priceTargetAction"),
            ))
    out.rating_changes.sort(key=lambda c: c.date, reverse=True)
    return out

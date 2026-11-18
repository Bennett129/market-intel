"""Turn SEC XBRL ``companyfacts`` into clean annual and quarterly series.

What makes this tricky:
- The same period is reported many times (original filing plus later comparatives). The
  latest-filed value is kept, so restatements win.
- Companies switch concepts over time (e.g. ``SalesRevenueNet`` →
  ``RevenueFromContractWithCustomer...``), so several concepts are merged in priority order.
- 10-Qs often report cash flows **year-to-date** (6M, 9M) and Q4 is never filed on its own.
  Quarters are derived by differencing cumulative periods that share a fiscal-year start.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

QUARTER_DAYS = range(80, 101)
YEAR_DAYS = range(350, 381)


@dataclass(frozen=True)
class Fact:
    start: date | None
    end: date
    val: float
    filed: date
    form: str

    @property
    def days(self) -> int | None:
        return None if self.start is None else (self.end - self.start).days + 1


def _parse(entry: dict[str, Any]) -> Fact | None:
    try:
        return Fact(
            start=date.fromisoformat(entry["start"]) if entry.get("start") else None,
            end=date.fromisoformat(entry["end"]),
            val=float(entry["val"]),
            filed=date.fromisoformat(entry["filed"]),
            form=entry.get("form", ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def collect(
    facts: dict[str, Any], concepts: list[str], unit: str, taxonomy: str = "us-gaap"
) -> list[Fact]:
    """Facts for the first concept that has data for a period, deduped per period."""
    by_period: dict[tuple[date | None, date], Fact] = {}
    tax = facts.get("facts", {}).get(taxonomy, {})
    for concept in concepts:  # priority order: earlier concepts win, later ones fill gaps
        entries = tax.get(concept, {}).get("units", {}).get(unit, [])
        best: dict[tuple[date | None, date], Fact] = {}
        for raw in entries:
            fact = _parse(raw)
            if fact is None:
                continue
            key = (fact.start, fact.end)
            if key not in best or fact.filed > best[key].filed:
                best[key] = fact
        for key, fact in best.items():
            by_period.setdefault(key, fact)
    return sorted(by_period.values(), key=lambda f: (f.end, f.start or f.end))


def annual(facts: list[Fact]) -> dict[date, Fact]:
    return {f.end: f for f in facts if f.days is not None and f.days in YEAR_DAYS}


def quarterly(facts: list[Fact]) -> dict[date, tuple[date, float]]:
    """Map quarter end → (quarter start, value), using direct quarters where reported and
    deriving the rest from cumulative (YTD / full-year) figures."""
    out: dict[date, tuple[date, float]] = {}
    durations = [f for f in facts if f.start is not None]
    for f in durations:
        if f.days in QUARTER_DAYS:
            out[f.end] = (f.start, f.val)  # type: ignore[assignment]

    by_start: dict[date, list[Fact]] = defaultdict(list)
    for f in durations:
        by_start[f.start].append(f)  # type: ignore[index]
    for group in by_start.values():
        group.sort(key=lambda f: f.end)
        prev: Fact | None = None
        for f in group:
            if prev is not None:
                q_start = prev.end + timedelta(days=1)
                q_days = (f.end - q_start).days + 1
                if q_days in QUARTER_DAYS and f.end not in out:
                    out[f.end] = (q_start, f.val - prev.val)
            prev = f

    # Q4 = full year − three standalone quarters (when no YTD figures were filed).
    for f in durations:
        if f.days not in YEAR_DAYS or f.end in out:
            continue
        inside = [(e, v) for e, (s, v) in out.items() if s >= f.start and e < f.end]  # type: ignore[operator]
        if len(inside) != 3:
            continue
        q_start = max(e for e, _ in inside) + timedelta(days=1)
        if (f.end - q_start).days + 1 in QUARTER_DAYS:
            out[f.end] = (q_start, f.val - sum(v for _, v in inside))
    return out


def instants(facts: list[Fact]) -> dict[date, float]:
    return {f.end: f.val for f in facts if f.start is None}


def latest_instant(facts: list[Fact]) -> tuple[date, float] | None:
    points = instants(facts)
    if not points:
        return None
    end = max(points)
    return end, points[end]

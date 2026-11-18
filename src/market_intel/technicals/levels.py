"""Support/resistance levels and a trend channel from OHLC bars.

1. **Pivots:** a bar is a pivot high (low) when its high (low) is the extreme of the ``window``
   bars on each side. A pivot less than half an ATR away from the previous opposite pivot is
   dropped, so noise inside a tight range doesn't count as structure.
2. **Levels:** pivots are clustered by price (tolerance = ``tolerance_atr`` x ATR). A cluster's
   strength grows with its number of touches and how recent they are, and shrinks when price has
   since closed decisively through it. The strongest well-separated clusters are returned.
3. **Channel:** least-squares fit of closes over the last ``channel_bars`` bars. The upper and
   lower lines are parallel to it, offset to the furthest pivot high/low, and are returned as two
   anchor points each, ready to draw.

Everything here is deterministic: the same bars always give the same output.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ..models import Channel, ChannelAnchor, Level, Levels

Pivot = tuple[int, str, float]  # (bar index, "high" | "low", price)


@dataclass(frozen=True)
class Bar:
    t: datetime
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


def atr(bars: Sequence[Bar], period: int = 14) -> float:
    if len(bars) < 2:
        return bars[0].h - bars[0].l if bars else 0.0
    trs = [
        max(b.h - b.l, abs(b.h - p.c), abs(b.l - p.c))
        for p, b in itertools.pairwise(bars)
    ]
    recent = trs[-period:]
    return sum(recent) / len(recent)


def pivots(bars: Sequence[Bar], window: int, min_swing: float) -> list[Pivot]:
    """Pivots in time order, alternating high/low."""
    raw: list[Pivot] = []
    for i in range(window, len(bars) - window):
        span = bars[i - window : i + window + 1]
        if bars[i].h >= max(b.h for b in span):
            raw.append((i, "high", bars[i].h))
        if bars[i].l <= min(b.l for b in span):
            raw.append((i, "low", bars[i].l))

    out: list[Pivot] = []
    for p in raw:
        if out and out[-1][1] == p[1]:
            # two highs (or lows) in a row: keep the more extreme one
            better = p[2] > out[-1][2] if p[1] == "high" else p[2] < out[-1][2]
            if better:
                out[-1] = p
            continue
        if out and abs(p[2] - out[-1][2]) < min_swing:
            continue
        out.append(p)
    return out


def _channel(bars: Sequence[Bar], piv: list[Pivot], n: int) -> Channel | None:
    start = max(0, len(bars) - n)
    seg = bars[start:]
    if len(seg) < 10:
        return None
    xs = range(len(seg))
    ys = [b.c for b in seg]
    mx, my = (len(seg) - 1) / 2, sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    icpt = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-12
    ss_res = sum((y - (icpt + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))

    def fit(i: int) -> float:
        return icpt + slope * (i - start)

    highs = [p for p in piv if p[0] >= start and p[1] == "high"]
    lows = [p for p in piv if p[0] >= start and p[1] == "low"]
    up = max(p[2] - fit(p[0]) for p in highs) if highs else max(
        b.h - fit(start + j) for j, b in enumerate(seg))
    dn = min(p[2] - fit(p[0]) for p in lows) if lows else min(
        b.l - fit(start + j) for j, b in enumerate(seg))

    first, last = start, len(bars) - 1
    days = max((bars[last].t - bars[first].t).total_seconds() / 86400, 1e-9)
    per_day = slope * (last - first) / days
    rel = per_day / my if my else 0.0
    direction = "flat" if abs(rel) < 0.0005 else ("up" if rel > 0 else "down")

    def line(offset: float) -> list[ChannelAnchor]:
        return [ChannelAnchor(t=bars[i].t, price=round(fit(i) + offset, 4)) for i in (first, last)]

    return Channel(direction=direction, slope_per_day=round(per_day, 6),
                   r2=round(1 - ss_res / ss_tot, 4), upper=line(up), middle=line(0.0),
                   lower=line(dn))


def compute_levels(
    symbol: str,
    bars: Sequence[Bar],
    *,
    window: int = 3,
    tolerance_atr: float = 0.6,
    max_levels: int = 6,
    channel_bars: int = 120,
) -> Levels:
    bars = sorted(bars, key=lambda b: b.t)
    n = len(bars)
    if n < 2 * window + 1:
        return Levels(symbol=symbol, bars_used=n)
    a = atr(bars)
    piv = pivots(bars, window, 0.5 * a)
    last_close = bars[-1].c
    tol = max(tolerance_atr * a, last_close * 0.002)

    clusters: list[list[Pivot]] = []
    for p in sorted(piv, key=lambda p: p[2]):
        if clusters and p[2] - _mean(clusters[-1]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    scored: list[Level] = []
    for c in clusters:
        price = _mean(c)
        idx = sorted(p[0] for p in c)
        recency = sum(math.exp(-(n - 1 - i) / (n / 2)) for i in idx)
        # closes since the last touch that went more than one tolerance through the level, on the
        # side opposite to where price sat at that touch: how often the level has been broken
        side = 1 if bars[idx[-1]].c >= price else -1
        breaks = sum(1 for b in bars[idx[-1] + 1 :] if (b.c - price) * side < -tol)
        scored.append(Level(
            price=round(price, 4),
            kind="support" if price <= last_close else "resistance",
            strength=(len(c) + recency) / (1 + 0.15 * breaks),
            touches=len(c),
            touch_times=[bars[i].t for i in idx],
            first=bars[idx[0]].t,
            last=bars[idx[-1]].t,
            broken=breaks > 0,
        ))

    chosen: list[Level] = []
    for lv in sorted(scored, key=lambda lv: lv.strength, reverse=True):
        if any(abs(lv.price - c.price) < 2 * tol for c in chosen):
            continue
        chosen.append(lv)
        if len(chosen) == max_levels:
            break
    top = max((lv.strength for lv in chosen), default=1.0) or 1.0

    return Levels(
        symbol=symbol,
        levels=[lv.model_copy(update={"strength": round(lv.strength / top, 3)})
                for lv in sorted(chosen, key=lambda lv: lv.price, reverse=True)],
        channel=_channel(bars, piv, channel_bars),
        atr=round(a, 4),
        last_close=last_close,
        bars_used=n,
        pivots=len(piv),
    )


def _mean(ps: list[Pivot]) -> float:
    return sum(p[2] for p in ps) / len(ps)

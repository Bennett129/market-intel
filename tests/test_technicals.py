import math
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from market_intel.api import create_app
from market_intel.technicals import Bar, compute_levels
from market_intel.technicals.levels import pivots

T0 = datetime(2026, 1, 2, 21, tzinfo=UTC)


def ranging(n: int = 200) -> list[Bar]:
    """Price oscillating between ~90 and ~110 (period 40 bars)."""
    out = []
    for i in range(n):
        mid = 100 + 10 * math.sin(2 * math.pi * i / 40)
        out.append(Bar(t=T0 + timedelta(days=i), o=mid, h=mid + 1, l=mid - 1, c=mid, v=1e6))
    return out


def trending(n: int = 150, slope: float = 0.5) -> list[Bar]:
    out = []
    for i in range(n):
        mid = 50 + slope * i + 3 * math.sin(2 * math.pi * i / 20)
        out.append(Bar(t=T0 + timedelta(days=i), o=mid, h=mid + 0.5, l=mid - 0.5, c=mid))
    return out


def test_range_gives_support_and_resistance_with_many_touches():
    lv = compute_levels("TEST", ranging())
    assert lv.bars_used == 200 and lv.pivots >= 8
    top, bottom = lv.levels[0], lv.levels[-1]
    assert abs(top.price - 111) < 1.0 and top.kind == "resistance"
    assert abs(bottom.price - 89) < 1.0 and bottom.kind == "support"
    assert top.touches >= 4 and bottom.touches >= 4
    assert max(x.strength for x in lv.levels) == 1.0
    # sorted high to low and well separated
    prices = [x.price for x in lv.levels]
    assert prices == sorted(prices, reverse=True)


def test_deterministic_and_order_independent():
    bars = ranging()
    a = compute_levels("TEST", bars)
    b = compute_levels("TEST", list(reversed(bars)))
    assert a == b


def test_channel_follows_trend():
    lv = compute_levels("UP", trending())
    ch = lv.channel
    assert ch is not None and ch.direction == "up"
    assert abs(ch.slope_per_day - 0.5) < 0.1
    assert ch.upper[0].price > ch.middle[0].price > ch.lower[0].price
    # parallel lines
    width0 = ch.upper[0].price - ch.lower[0].price
    width1 = ch.upper[1].price - ch.lower[1].price
    assert abs(width0 - width1) < 1e-3
    assert compute_levels("DN", trending(slope=-0.3)).channel.direction == "down"


def test_too_few_bars_returns_empty():
    lv = compute_levels("X", ranging(5))
    assert lv.levels == [] and lv.channel is None and lv.bars_used == 5


def test_pivots_alternate_and_ignore_small_swings():
    piv = pivots(ranging(), window=3, min_swing=2.0)
    kinds = [p[1] for p in piv]
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False))


def test_broken_level_is_flagged():
    # range for 100 bars, then a breakdown far below it
    bars = ranging(100)
    for i in range(100, 140):
        bars.append(Bar(t=T0 + timedelta(days=i), o=70, h=71, l=69, c=70))
    lv = compute_levels("BRK", bars)
    old_support = [x for x in lv.levels if 85 < x.price < 95]
    assert old_support and old_support[0].broken and old_support[0].kind == "resistance"


def test_post_levels_endpoint_works_with_yahoo_off(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    client = TestClient(create_app(mi))
    body = {"symbol": "test", "bars": [
        {"t": b.t.isoformat(), "o": b.o, "h": b.h, "l": b.l, "c": b.c} for b in ranging()
    ]}
    r = client.post("/v1/technicals/levels", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "TEST" and len(data["levels"]) >= 2
    assert data["meta"]["yahoo_enabled"] is False
    # GET needs Yahoo history
    assert client.get("/v1/tickers/AAPL/levels").status_code == 503
    assert client.post("/v1/technicals/levels", json={"bars": []}).status_code == 422

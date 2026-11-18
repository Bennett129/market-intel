from datetime import date, datetime

import pandas as pd
import pytest

from market_intel.datasets.analysts import build_analysts
from market_intel.datasets.estimates import build_estimates
from market_intel.datasets.insiders import build_insiders
from market_intel.errors import DatasetUnavailable, SymbolNotFound


def test_profile_from_edgar_with_yahoo_off(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    p = mi.profile("aapl")
    assert p.symbol == "AAPL" and p.name == "Apple Inc." and p.cik == 320193
    assert p.address.city == "CUPERTINO" and p.sector is None
    assert p.meta.sources == ["sec_edgar"] and not p.meta.yahoo_enabled
    assert any("yahoo disabled" in w for w in p.meta.warnings)


def test_unknown_symbol(make_mi):
    mi, _ = make_mi()
    with pytest.raises(SymbolNotFound):
        mi.profile("ZZZZ")


def test_fundamentals_with_supplied_price(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    f = mi.fundamentals("AAPL", price=300)
    assert [q.period_end.isoformat() for q in f.quarterly][:2] == ["2026-09-26", "2026-06-27"]
    assert f.ttm["revenue"] == 400 and f.ttm["net_income"] == pytest.approx(100)
    assert f.ttm["eps_diluted"] == pytest.approx(10.0)
    assert f.shares_outstanding == 10
    r = f.ratios
    assert r["market_cap"] == 3000 and r["pe"] == pytest.approx(30)
    assert r["price_to_sales"] == 7.5 and r["price_to_book"] == 60
    assert r["net_margin"] == pytest.approx(0.25)
    assert f.annual[0].values["revenue"] == 400 and f.annual[0].values["stockholders_equity"] == 50


def test_insiders_and_summary(make_mi):
    mi, _ = make_mi()
    ins = build_insiders(mi.sec, "AAPL", today=date(2026, 11, 18))
    assert ins.filings_scanned == 2
    assert ins.transactions[0].insider_name == "DOE JANE" and ins.transactions[0].code == "P"
    s30, s90 = ins.summary[0], ins.summary[1]
    assert (s30.buys, s30.buy_value, s30.sells) == (1, 200_000, 0)
    assert (s90.sells, s90.sell_value, s90.planned_sell_value) == (1, 250_500, 250_500)
    assert s90.net_value == pytest.approx(-50_500)


def test_form4_documents_are_cached_forever(make_mi):
    mi, fake = make_mi()
    mi.insiders("AAPL")
    n = len(fake.calls)
    mi.insiders("AAPL")
    assert len(fake.calls) == n  # second run: no network


def test_ownership_edgar_only(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    o = mi.ownership("AAPL")
    assert o.beneficial_owner_filings[0].filer_name == "VANGUARD GROUP INC"
    assert {h.name: h.shares for h in o.insider_holdings} == {
        "DOE JANE": 12000, "COOK TIMOTHY D": 3_280_000}
    assert o.top_institutions == [] and o.institutions_pct is None


def test_events_edgar_only(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    ev = mi.events("AAPL", start=date(2026, 1, 1), end=date(2027, 1, 1))
    types = {(e.type, e.date.isoformat()) for e in ev.past}
    assert ("earnings_release", "2026-10-30") in types and ("filing", "2026-08-01") in types


@pytest.mark.parametrize("method", ["analysts", "estimates", "corporate_actions"])
def test_yahoo_only_datasets_unavailable_when_disabled(make_mi, method):
    mi, _ = make_mi(yahoo_enabled=False)
    with pytest.raises(DatasetUnavailable, match="MI_YAHOO_ENABLED=false"):
        getattr(mi, method)("AAPL")


def test_stale_cache_served_when_upstream_fails(make_mi):
    mi, fake = make_mi()
    mi.sec.ticker_map()  # warm the ticker map
    mi.cache._dc.set("sec:subs:320193", {"v": {"name": "Old Name"}, "t": 0})  # long expired
    fake.fail = True
    p = mi.profile("AAPL")
    assert p.name == "Old Name" and p.meta.stale
    assert any("serving cached data" in w for w in p.meta.warnings)


class FakeYahoo:
    """Returns DataFrames shaped like yfinance 1.8 output."""

    enabled = True

    def __init__(self, data):
        self.data = data

    def get(self, symbol, name, ttl, call):
        return self.data[name]

    optional = get


def test_estimates_normalisation():
    idx = pd.Index(["0q", "+1q"], name="period")
    y = FakeYahoo({
        "earnings_estimate": pd.DataFrame({"avg": [2.9, 2.1], "low": [2.8, 1.8], "high": [3.1, 2.4],
                                           "yearAgoEps": [2.84, 2.01], "numberOfAnalysts": [25, 23],
                                           "growth": [0.025, 0.07]}, index=idx),
        "revenue_estimate": pd.DataFrame({"avg": [1.5e11, 1.2e11], "yearAgoRevenue": [1.4e11, 1.1e11],
                                          "numberOfAnalysts": [23, 21]}, index=idx),
        "eps_trend": pd.DataFrame({"current": [2.0, 2.1], "7daysAgo": [2, 2], "30daysAgo": [1.6, 2.1],
                                   "60daysAgo": [1, 1], "90daysAgo": [2.5, 2.1]}, index=idx),
        "eps_revisions": pd.DataFrame({"upLast7days": [10, 1], "upLast30days": [11, 2],
                                       "downLast30days": [4, 13], "downLast7Days": [4, 13]}, index=idx),
        "growth_estimates": pd.DataFrame({"stockTrend": [0.02, 0.07], "indexTrend": [0.29, 0.27]},
                                         index=idx),
        "earnings_history": pd.DataFrame(
            {"epsActual": [2.84], "epsEstimate": [2.67], "surprisePercent": [0.0634]},
            index=pd.Index([pd.Timestamp("2025-12-31")], name="quarter")),
    })
    e = build_estimates(y, "AAPL")
    assert e.eps[0].analysts == 25 and e.revenue[0].year_ago == 1.4e11
    assert e.eps_trend[0].change_30d == pytest.approx(0.25)
    assert e.eps_trend[0].change_90d == pytest.approx(-0.2)
    assert e.eps_revisions[1].down_7d == 13
    assert e.earnings_history[0].surprise == pytest.approx(0.0634)


def test_analysts_normalisation():
    grades = pd.DataFrame(
        {"Firm": ["A", "B", "C"], "ToGrade": ["Buy", "Hold", "Buy"], "FromGrade": ["Hold", "Buy", ""],
         "Action": ["up", "down", "up"], "priceTargetAction": ["Raises", "Lowers", "Announces"],
         "currentPriceTarget": [400.0, 300.0, 350.0], "priorPriceTarget": [380.0, 320.0, 0.0]},
        index=pd.Index(pd.to_datetime(["2026-11-11", "2026-10-01", "2026-01-01"]), name="GradeDate"),
    )
    recs = pd.DataFrame({"period": ["0m"], "strongBuy": [6], "buy": [20], "hold": [13],
                         "sell": [3], "strongSell": [3]})
    y = FakeYahoo({"analyst_price_targets": {"current": 350.0, "mean": 385.0, "low": 250.0,
                                             "high": 425.0, "median": 355.0},
                   "recommendations": recs, "upgrades_downgrades": grades})
    a = build_analysts(y, "AAPL", now=datetime(2026, 11, 18))
    assert a.price_targets.upside_to_mean == pytest.approx(0.1)
    assert a.recommendation_trend[0].score == pytest.approx((6 + 40 + 39 + 12 + 15) / 45, abs=1e-3)
    assert a.net_upgrades_90d == 0  # one up, one down in window; the Jan upgrade is outside
    assert a.rating_changes[-1].prior_price_target is None and a.rating_changes[-1].from_grade is None

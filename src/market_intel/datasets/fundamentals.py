"""Financial statements from SEC XBRL company facts (EDGAR only, so they work with Yahoo off).

Valuation ratios need a share price. Pass ``price=`` (e.g. the trading app sends its Alpaca
price). If no price is given and Yahoo is enabled, Yahoo's last price is used. Otherwise the
ratios that need a price are omitted.
"""

from __future__ import annotations

from datetime import date

from ..cache import TTL_MINUTE
from ..models import Fundamentals, StatementPeriod
from ..parsers import xbrl
from ..providers import SecClient, YahooClient
from ..providers.sec import normalize_symbol

USD, PER_SHARE = "USD", "USD/shares"

# metric → (concepts in priority order, unit)
DURATION: dict[str, tuple[list[str], str]] = {
    "revenue": (
        [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ],
        USD,
    ),
    "cost_of_revenue": (["CostOfRevenue", "CostOfGoodsAndServicesSold"], USD),
    "gross_profit": (["GrossProfit"], USD),
    "research_and_development": (["ResearchAndDevelopmentExpense"], USD),
    "selling_general_admin": (["SellingGeneralAndAdministrativeExpense"], USD),
    "operating_income": (["OperatingIncomeLoss"], USD),
    "net_income": (["NetIncomeLoss", "ProfitLoss"], USD),
    "eps_basic": (["EarningsPerShareBasic"], PER_SHARE),
    "eps_diluted": (["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"], PER_SHARE),
    "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], USD),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment"], USD),
    "dividends_paid": (["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"], USD),
    "share_buybacks": (["PaymentsForRepurchaseOfCommonStock"], USD),
}

INSTANT: dict[str, tuple[list[str], str]] = {
    "total_assets": (["Assets"], USD),
    "total_liabilities": (["Liabilities"], USD),
    "stockholders_equity": (
        ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        USD,
    ),
    "cash": (
        ["CashAndCashEquivalentsAtCarryingValue",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
        USD,
    ),
    "current_assets": (["AssetsCurrent"], USD),
    "current_liabilities": (["LiabilitiesCurrent"], USD),
    "long_term_debt": (["LongTermDebtNoncurrent", "LongTermDebt"], USD),
}

MAX_ANNUAL, MAX_QUARTERS = 10, 12


def _derive(values: dict[str, float | None]) -> None:
    rev, cor = values.get("revenue"), values.get("cost_of_revenue")
    if values.get("gross_profit") is None and rev is not None and cor is not None:
        values["gross_profit"] = rev - cor
    ocf, capex = values.get("operating_cash_flow"), values.get("capex")
    values["free_cash_flow"] = ocf - capex if ocf is not None and capex is not None else None


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def build_fundamentals(
    sec: SecClient, yahoo: YahooClient, symbol: str, price: float | None = None
) -> Fundamentals:
    sym = normalize_symbol(symbol)
    facts = sec.company_facts(sec.cik(sym))

    dur = {m: xbrl.collect(facts, c, u) for m, (c, u) in DURATION.items()}
    inst = {m: xbrl.instants(xbrl.collect(facts, c, u)) for m, (c, u) in INSTANT.items()}
    ann = {m: xbrl.annual(f) for m, f in dur.items()}
    qtr = {m: xbrl.quarterly(f) for m, f in dur.items()}

    def period_rows(series: dict[str, dict], kind: str, limit: int) -> list[StatementPeriod]:
        ends = sorted({e for s in series.values() for e in s}, reverse=True)[:limit]
        rows = []
        for end in ends:
            values: dict[str, float | None] = {}
            start: date | None = None
            for m, s in series.items():
                item = s.get(end)
                if item is None:
                    values[m] = None
                elif kind == "FY":
                    values[m], start = item.val, start or item.start
                else:
                    start = start or item[0]
                    values[m] = item[1]
            for m, points in inst.items():
                values[m] = points.get(end)
            _derive(values)
            rows.append(StatementPeriod(period_start=start, period_end=end,
                                        fiscal_period=kind, values=values))  # type: ignore[arg-type]
        return rows

    annual_rows = period_rows(ann, "FY", MAX_ANNUAL)
    quarterly_rows = period_rows(qtr, "Q", MAX_QUARTERS)

    # TTM = sum of the latest four contiguous quarters (EPS is an approximation).
    ttm: dict[str, float | None] = {}
    last4 = quarterly_rows[:4]
    contiguous = (
        len(last4) == 4
        and last4[3].period_start is not None
        and 350 <= (last4[0].period_end - last4[3].period_start).days + 1 <= 380
    )
    if contiguous:
        for m in DURATION:
            vals = [r.values.get(m) for r in last4]
            ttm[m] = sum(vals) if all(v is not None for v in vals) else None  # type: ignore[misc]
        _derive(ttm)

    shares_pt = xbrl.latest_instant(
        xbrl.collect(facts, ["EntityCommonStockSharesOutstanding"], "shares", taxonomy="dei")
    ) or xbrl.latest_instant(xbrl.collect(facts, ["CommonStockSharesOutstanding"], "shares"))

    result = Fundamentals(symbol=sym, annual=annual_rows, quarterly=quarterly_rows, ttm=ttm)
    if shares_pt:
        result.shares_outstanding_as_of, result.shares_outstanding = shares_pt

    if price is None:
        fi = yahoo.optional(sym, "last_price", TTL_MINUTE * 5,
                            lambda t: float(t.fast_info.last_price))
        price = fi
    result.price_used = price

    latest = {m: (max(p.items())[1] if p else None) for m, p in inst.items()}
    equity = latest.get("stockholders_equity")
    mcap = price * result.shares_outstanding if price and result.shares_outstanding else None
    eps = ttm.get("eps_diluted")
    result.ratios = {
        "market_cap": mcap,
        "pe": _div(price, eps) if eps and eps > 0 else None,
        "price_to_sales": _div(mcap, ttm.get("revenue")),
        "price_to_book": _div(mcap, equity) if equity and equity > 0 else None,
        "fcf_yield": _div(ttm.get("free_cash_flow"), mcap),
        "gross_margin": _div(ttm.get("gross_profit"), ttm.get("revenue")),
        "operating_margin": _div(ttm.get("operating_income"), ttm.get("revenue")),
        "net_margin": _div(ttm.get("net_income"), ttm.get("revenue")),
        "return_on_equity": _div(ttm.get("net_income"), equity),
        "debt_to_equity": _div(latest.get("long_term_debt"), equity),
        "current_ratio": _div(latest.get("current_assets"), latest.get("current_liabilities")),
    }
    return result

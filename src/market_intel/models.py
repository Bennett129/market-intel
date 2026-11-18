"""Normalised output schemas.

Conventions:
- All percentages are **fractions** (0.058 == 5.8%), whatever the upstream format.
- Monetary values are in the reporting currency (``currency`` field where relevant, usually USD).
- Every top-level dataset carries ``meta``: sources, freshness, staleness, warnings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Meta(BaseModel):
    sources: list[str] = Field(default_factory=list)
    fetched_at: datetime | None = None
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    yahoo_enabled: bool = True


class Dataset(BaseModel):
    symbol: str
    meta: Meta = Field(default_factory=Meta)


# --- Profile ------------------------------------------------------------------------------


class Address(BaseModel):
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str | None = None


class Profile(Dataset):
    name: str
    cik: int | None = None
    tickers: list[str] = Field(default_factory=list)
    exchanges: list[str] = Field(default_factory=list)
    sic: str | None = None
    sic_description: str | None = None
    fiscal_year_end: str | None = None  # MMDD
    state_of_incorporation: str | None = None
    filer_category: str | None = None
    address: Address | None = None
    phone: str | None = None
    # Yahoo enrichment
    sector: str | None = None
    industry: str | None = None
    summary: str | None = None
    employees: int | None = None
    website: str | None = None
    currency: str | None = None
    market_cap: float | None = None


# --- Fundamentals -------------------------------------------------------------------------


class StatementPeriod(BaseModel):
    period_start: date | None = None
    period_end: date
    fiscal_period: Literal["FY", "Q"]
    values: dict[str, float | None]


class Fundamentals(Dataset):
    currency: str = "USD"
    annual: list[StatementPeriod] = Field(default_factory=list)
    quarterly: list[StatementPeriod] = Field(default_factory=list)
    ttm: dict[str, float | None] = Field(default_factory=dict)
    shares_outstanding: float | None = None
    shares_outstanding_as_of: date | None = None
    price_used: float | None = None
    ratios: dict[str, float | None] = Field(default_factory=dict)


# --- Insiders (SEC Form 4) ----------------------------------------------------------------


class InsiderTransaction(BaseModel):
    filing_date: date
    transaction_date: date | None
    insider_name: str
    insider_cik: str | None = None
    roles: list[str] = Field(default_factory=list)
    security: str | None = None
    code: str | None = None
    code_description: str | None = None
    acquired_disposed: Literal["A", "D"] | None = None
    shares: float | None = None
    price: float | None = None
    value: float | None = None
    shares_owned_after: float | None = None
    direct_ownership: bool | None = None
    is_derivative: bool = False
    is_open_market: bool = False  # code P (purchase) or S (sale)
    is_10b5_1_plan: bool = False  # pre-scheduled trading plan: less informative as a signal
    accession: str
    url: str


class InsiderWindowSummary(BaseModel):
    days: int
    buys: int = 0
    sells: int = 0
    buy_value: float = 0.0
    sell_value: float = 0.0
    net_value: float = 0.0
    distinct_buyers: int = 0
    distinct_sellers: int = 0
    planned_sell_value: float = 0.0  # 10b5-1 portion of sell_value


class InsiderActivity(Dataset):
    transactions: list[InsiderTransaction] = Field(default_factory=list)
    summary: list[InsiderWindowSummary] = Field(default_factory=list)
    filings_scanned: int = 0


# --- Ownership ----------------------------------------------------------------------------


class Holder(BaseModel):
    holder: str
    shares: float | None = None
    pct_held: float | None = None
    value: float | None = None
    pct_change: float | None = None
    date_reported: date | None = None


class BeneficialOwnerFiling(BaseModel):
    form: str
    filing_date: date
    filer_name: str | None = None
    accession: str
    url: str


class InsiderHolding(BaseModel):
    name: str
    roles: list[str] = Field(default_factory=list)
    shares: float
    as_of: date


class Ownership(Dataset):
    insiders_pct: float | None = None
    institutions_pct: float | None = None
    institutions_float_pct: float | None = None
    institutions_count: int | None = None
    top_institutions: list[Holder] = Field(default_factory=list)
    top_funds: list[Holder] = Field(default_factory=list)
    beneficial_owner_filings: list[BeneficialOwnerFiling] = Field(default_factory=list)
    insider_holdings: list[InsiderHolding] = Field(default_factory=list)


# --- Analysts -----------------------------------------------------------------------------


class PriceTargets(BaseModel):
    current_price: float | None = None
    low: float | None = None
    high: float | None = None
    mean: float | None = None
    median: float | None = None
    upside_to_mean: float | None = None


class RecommendationPeriod(BaseModel):
    period: str  # "0m", "-1m", ...
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0
    score: float | None = None  # 1 (strong buy) … 5 (strong sell)


class RatingChange(BaseModel):
    date: datetime
    firm: str
    to_grade: str | None = None
    from_grade: str | None = None
    action: str | None = None  # up | down | main | init | reit
    price_target: float | None = None
    prior_price_target: float | None = None
    price_target_action: str | None = None


class Analysts(Dataset):
    price_targets: PriceTargets | None = None
    recommendation_trend: list[RecommendationPeriod] = Field(default_factory=list)
    rating_changes: list[RatingChange] = Field(default_factory=list)
    net_upgrades_90d: int = 0


# --- Estimates ----------------------------------------------------------------------------


class EstimateRow(BaseModel):
    period: str  # 0q, +1q, 0y, +1y
    avg: float | None = None
    low: float | None = None
    high: float | None = None
    year_ago: float | None = None
    analysts: int | None = None
    growth: float | None = None


class EpsTrendRow(BaseModel):
    period: str
    current: float | None = None
    d7: float | None = None
    d30: float | None = None
    d60: float | None = None
    d90: float | None = None
    change_30d: float | None = None  # fractional change of the estimate over 30 days
    change_90d: float | None = None


class EpsRevisionsRow(BaseModel):
    period: str
    up_7d: int | None = None
    up_30d: int | None = None
    down_7d: int | None = None
    down_30d: int | None = None


class GrowthRow(BaseModel):
    period: str
    stock: float | None = None
    index: float | None = None


class EarningsSurprise(BaseModel):
    quarter_end: date
    eps_actual: float | None = None
    eps_estimate: float | None = None
    surprise: float | None = None


class Estimates(Dataset):
    eps: list[EstimateRow] = Field(default_factory=list)
    revenue: list[EstimateRow] = Field(default_factory=list)
    eps_trend: list[EpsTrendRow] = Field(default_factory=list)
    eps_revisions: list[EpsRevisionsRow] = Field(default_factory=list)
    growth: list[GrowthRow] = Field(default_factory=list)
    earnings_history: list[EarningsSurprise] = Field(default_factory=list)


# --- Events & corporate actions -----------------------------------------------------------

EventType = Literal[
    "earnings", "earnings_release", "ex_dividend", "dividend_payment", "split", "filing"
]


class Event(BaseModel):
    date: date
    type: EventType
    title: str
    source: str
    confirmed: bool = True
    url: str | None = None
    details: dict[str, float | str | None] = Field(default_factory=dict)


class Events(Dataset):
    upcoming: list[Event] = Field(default_factory=list)
    past: list[Event] = Field(default_factory=list)


class CorporateAction(BaseModel):
    date: date
    type: Literal["dividend", "split"]
    value: float  # cash per share for dividends, ratio (new/old) for splits


class CorporateActions(Dataset):
    actions: list[CorporateAction] = Field(default_factory=list)

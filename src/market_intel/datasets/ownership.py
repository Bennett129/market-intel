"""Ownership.

- EDGAR (always on): Schedule 13D/13G filings (≥5% beneficial owners) and current insider
  holdings from Form 4 data.
- Yahoo (optional): ownership breakdown and top institutional / mutual-fund holders.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .. import context
from ..cache import TTL_HOUR
from ..errors import MarketIntelError
from ..models import BeneficialOwnerFiling, Holder, InsiderHolding, Ownership
from ..parsers.frames import as_date, integer, num, pick, rows
from ..providers import SecClient, YahooClient
from ..providers.sec import normalize_symbol, recent_filings
from .insiders import build_insiders

BENEFICIAL_FORMS = {
    f"{prefix} 13{kind}{amend}"
    for prefix in ("SC", "SCHEDULE")
    for kind in ("D", "G")
    for amend in ("", "/A")
}
MAX_13DG = 15
_FILER = [
    re.compile(r"FILED BY:.*?COMPANY CONFORMED NAME:\s*([^\n<]+)", re.DOTALL),
    re.compile(r"<FILED-BY>.*?<CONFORMED-NAME>([^\n<]+)", re.DOTALL),
]


def _filer_name(header: str) -> str | None:
    text = html.unescape(header)
    for pattern in _FILER:
        if m := pattern.search(text):
            return m.group(1).strip()
    return None


def _holders(df: Any) -> list[Holder]:
    return [
        Holder(
            holder=str(pick(r, "Holder") or "Unknown"),
            shares=num(pick(r, "Shares")),
            pct_held=num(pick(r, "pctHeld", "% Out")),
            value=num(pick(r, "Value")),
            pct_change=num(pick(r, "pctChange")),
            date_reported=as_date(pick(r, "Date Reported")),
        )
        for r in rows(df)
    ]


def build_ownership(sec: SecClient, yahoo: YahooClient, symbol: str) -> Ownership:
    sym = normalize_symbol(symbol)
    out = Ownership(symbol=sym)
    cik = sec.cik(sym)

    for f in [f for f in recent_filings(sec.submissions(cik)) if f.form in BENEFICIAL_FORMS][:MAX_13DG]:
        try:
            filer = _filer_name(sec.filing_header(cik, f))
        except MarketIntelError:
            filer = None
        out.beneficial_owner_filings.append(
            BeneficialOwnerFiling(form=f.form, filing_date=f.filing_date, filer_name=filer,
                                  accession=f.accession, url=sec.filing_url(cik, f))
        )

    # Latest reported post-transaction holding per insider (direct + indirect summed).
    latest: dict[tuple[str, bool | None], tuple[Any, float, list[str]]] = {}
    for t in build_insiders(sec, sym, limit=60, days=730).transactions:
        if t.is_derivative or t.shares_owned_after is None:
            continue
        when = t.transaction_date or t.filing_date
        key = (t.insider_name, t.direct_ownership)
        if key not in latest or when > latest[key][0]:
            latest[key] = (when, t.shares_owned_after, t.roles)
    per_person: dict[str, InsiderHolding] = {}
    for (name, _), (when, shares, roles) in latest.items():
        h = per_person.setdefault(name, InsiderHolding(name=name, roles=roles, shares=0, as_of=when))
        h.shares += shares
        h.as_of = max(h.as_of, when)
    out.insider_holdings = sorted(per_person.values(), key=lambda h: h.shares, reverse=True)

    if not yahoo.enabled:
        context.warn("yahoo disabled: institutional holders and ownership breakdown omitted")
        return out

    major = yahoo.optional(sym, "major_holders", TTL_HOUR * 12, lambda t: t.major_holders)
    breakdown = {str(r.get("breakdown")): r.get("value") for r in rows(major, "breakdown")}
    out.insiders_pct = num(breakdown.get("insidersPercentHeld"))
    out.institutions_pct = num(breakdown.get("institutionsPercentHeld"))
    out.institutions_float_pct = num(breakdown.get("institutionsFloatPercentHeld"))
    out.institutions_count = integer(breakdown.get("institutionsCount"))
    out.top_institutions = _holders(
        yahoo.optional(sym, "institutional_holders", TTL_HOUR * 12, lambda t: t.institutional_holders)
    )
    out.top_funds = _holders(
        yahoo.optional(sym, "mutualfund_holders", TTL_HOUR * 12, lambda t: t.mutualfund_holders)
    )
    return out

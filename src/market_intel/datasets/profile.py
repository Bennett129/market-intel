"""Company profile. Primary: SEC submissions. Enrichment: Yahoo ``info`` (sector, summary…).
If the symbol isn't an SEC registrant (e.g. some ETFs or foreign tickers), Yahoo alone is used
when enabled."""

from __future__ import annotations

from typing import Any

from ..cache import TTL_DAY
from ..errors import SymbolNotFound
from ..models import Address, Profile
from ..parsers.frames import integer, num
from ..providers import SecClient, YahooClient
from ..providers.sec import normalize_symbol


def _yahoo_info(yahoo: YahooClient, symbol: str) -> dict[str, Any] | None:
    return yahoo.optional(symbol, "info", TTL_DAY, lambda t: dict(t.info or {}))


def build_profile(sec: SecClient, yahoo: YahooClient, symbol: str) -> Profile:
    sym = normalize_symbol(symbol)
    try:
        cik = sec.cik(sym)
    except SymbolNotFound:
        info = _yahoo_info(yahoo, sym) if yahoo.enabled else None
        if not info or not (info.get("longName") or info.get("shortName")):
            raise
        profile = Profile(symbol=sym, name=info.get("longName") or info.get("shortName"))
        _enrich(profile, info)
        return profile

    s = sec.submissions(cik)
    addr = (s.get("addresses") or {}).get("business") or {}
    profile = Profile(
        symbol=sym,
        name=s.get("name") or sym,
        cik=cik,
        tickers=s.get("tickers") or [],
        exchanges=[e for e in (s.get("exchanges") or []) if e],
        sic=s.get("sic") or None,
        sic_description=s.get("sicDescription") or None,
        fiscal_year_end=s.get("fiscalYearEnd") or None,
        state_of_incorporation=s.get("stateOfIncorporation") or None,
        filer_category=s.get("category") or None,
        address=Address(
            street=addr.get("street1"),
            city=addr.get("city"),
            state=addr.get("stateOrCountry"),
            zip=addr.get("zipCode"),
            country=addr.get("country") or None,
        )
        if addr
        else None,
        phone=s.get("phone") or None,
        website=s.get("website") or None,
    )
    if info := _yahoo_info(yahoo, sym):
        _enrich(profile, info)
    return profile


def _enrich(profile: Profile, info: dict[str, Any]) -> None:
    profile.sector = info.get("sector") or profile.sector
    profile.industry = info.get("industry") or profile.industry
    profile.summary = info.get("longBusinessSummary") or profile.summary
    profile.employees = integer(info.get("fullTimeEmployees")) or profile.employees
    profile.website = info.get("website") or profile.website
    profile.currency = info.get("currency") or profile.currency
    profile.market_cap = num(info.get("marketCap")) or profile.market_cap

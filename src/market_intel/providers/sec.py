"""SEC EDGAR client: free, official, public-domain data. Always enabled.

Endpoints used:
- https://www.sec.gov/files/company_tickers.json        ticker → CIK
- https://data.sec.gov/submissions/CIK##########.json  company profile + filing index
- https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json  reported financials (XBRL)
- https://www.sec.gov/Archives/edgar/data/...          individual filing documents
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from ..cache import TTL_DAY, TTL_HOUR, Cache
from ..config import Settings
from ..errors import ConfigError, NotFound, SymbolNotFound, UpstreamError
from ..ratelimit import CircuitBreaker, RateLimiter

SOURCE = "sec_edgar"
WWW = "https://www.sec.gov"
DATA = "https://data.sec.gov"


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    items: str

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def recent_filings(submissions: dict[str, Any]) -> list[Filing]:
    """Turn the column-oriented ``filings.recent`` block into rows (newest first)."""
    recent = submissions.get("filings", {}).get("recent", {})
    cols = ("accessionNumber", "form", "filingDate", "reportDate", "primaryDocument", "items")
    columns = [recent.get(c, []) for c in cols]
    rows: list[Filing] = []
    for acc, form, filed, report, doc, items in zip(*columns, strict=False):
        filed_d = _parse_date(filed)
        if filed_d is None:
            continue
        rows.append(Filing(acc, form, filed_d, _parse_date(report), doc or "", items or ""))
    return rows


class SecClient:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self._settings = settings
        self._cache = cache
        self._limiter = RateLimiter(settings.sec_max_rps)
        self._breaker = CircuitBreaker(
            SOURCE, settings.breaker_threshold, settings.breaker_cooldown_s
        )
        self._http: httpx.Client | None = None

    # -- transport -------------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        if self._http is None:
            ua = self._settings.sec_user_agent.strip()
            if not ua:
                raise ConfigError(
                    "MI_SEC_USER_AGENT is not set. SEC requires a User-Agent with contact "
                    'details, e.g. MI_SEC_USER_AGENT="market-intel you@example.com"'
                )
            self._http = httpx.Client(
                headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
                timeout=20.0,
                follow_redirects=True,
            )
        return self._http

    def _get(self, url: str) -> httpx.Response:
        client = self._client()
        self._breaker.before()
        self._limiter.acquire()
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            self._breaker.failure()
            raise UpstreamError(f"{SOURCE}: {type(exc).__name__} for {url}") from exc
        if resp.status_code == 404:
            self._breaker.success()
            raise NotFound(f"{SOURCE}: not found: {url}")
        if resp.status_code in (403, 429) or resp.status_code >= 500:
            self._breaker.failure()
            raise UpstreamError(f"{SOURCE}: HTTP {resp.status_code} for {url}")
        self._breaker.success()
        return resp

    def _json(self, url: str, key: str, ttl: float | None) -> Any:
        return self._cache.get_or_fetch(key, ttl, lambda: self._get(url).json(), SOURCE)

    def _text(self, url: str, key: str, ttl: float | None) -> str:
        return self._cache.get_or_fetch(key, ttl, lambda: self._get(url).text, SOURCE)

    # -- endpoints -------------------------------------------------------------------------

    def ticker_map(self) -> dict[str, dict[str, Any]]:
        data = self._json(f"{WWW}/files/company_tickers.json", "sec:tickers", TTL_DAY)
        return {row["ticker"].upper(): row for row in data.values()}

    def cik(self, symbol: str) -> int:
        row = self.ticker_map().get(normalize_symbol(symbol))
        if row is None:
            raise SymbolNotFound(f"{symbol!r} is not a known SEC registrant ticker")
        return int(row["cik_str"])

    def submissions(self, cik: int) -> dict[str, Any]:
        return self._json(f"{DATA}/submissions/CIK{cik:010d}.json", f"sec:subs:{cik}", TTL_HOUR / 2)

    def company_facts(self, cik: int) -> dict[str, Any]:
        url = f"{DATA}/api/xbrl/companyfacts/CIK{cik:010d}.json"
        try:
            return self._json(url, f"sec:facts:{cik}", TTL_HOUR * 6)
        except NotFound:
            return {}  # e.g. foreign private issuers / funds without XBRL company facts

    def filing_url(self, cik: int, filing: Filing, document: str | None = None) -> str:
        doc = filing.primary_document if document is None else document
        return f"{WWW}/Archives/edgar/data/{cik}/{filing.accession_nodash}/{doc}"

    def filing_document(self, cik: int, filing: Filing, document: str) -> str:
        """Filed documents are immutable, so they are cached forever."""
        url = self.filing_url(cik, filing, document)
        return self._text(url, f"sec:doc:{filing.accession}:{document}", None)

    def filing_header(self, cik: int, filing: Filing) -> str:
        url = self.filing_url(cik, filing, f"{filing.accession}-index-headers.html")
        return self._text(url, f"sec:hdr:{filing.accession}", None)

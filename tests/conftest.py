from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from market_intel import MarketIntel
from market_intel.errors import NotFound

FIXTURES = Path(__file__).parent / "fixtures"
CIK = 320193
ACC_BUY = "0001140361-26-000001"
ACC_SELL = "0000320193-26-000002"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text()


def fact(start: str | None, end: str, val: float, filed: str, form: str = "10-Q") -> dict:
    d = {"end": end, "val": val, "filed": filed, "form": form}
    if start:
        d["start"] = start
    return d


BUY_FORM4 = """<?xml version="1.0"?><ownershipDocument>
<reportingOwner><reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName>
</reportingOwnerId><reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>
</reportingOwner><nonDerivativeTable><nonDerivativeTransaction>
<securityTitle><value>Common Stock</value></securityTitle>
<transactionDate><value>2026-11-10</value></transactionDate>
<transactionCoding><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>2000</value></transactionShares>
<transactionPricePerShare><value>100</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><sharesOwnedFollowingTransaction><value>12000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""


def sec_responses() -> dict[str, Any]:
    nodash_buy, nodash_sell = ACC_BUY.replace("-", ""), ACC_SELL.replace("-", "")
    arch = f"https://www.sec.gov/Archives/edgar/data/{CIK}"
    submissions = {
        "cik": str(CIK), "name": "Apple Inc.", "sic": "3571", "sicDescription": "Electronic Computers",
        "tickers": ["AAPL"], "exchanges": ["Nasdaq"], "fiscalYearEnd": "0926",
        "stateOfIncorporation": "CA", "category": "Large accelerated filer", "phone": "(408) 996-1010",
        "addresses": {"business": {"street1": "ONE APPLE PARK WAY", "city": "CUPERTINO",
                                   "stateOrCountry": "CA", "zipCode": "95014"}},
        "filings": {"recent": {
            "accessionNumber": [ACC_BUY, ACC_SELL, "0000320193-26-000003", "0000320193-26-000004",
                                "0000950103-26-000005"],
            "form": ["4", "4", "8-K", "10-Q", "SC 13G/A"],
            "filingDate": ["2026-11-12", "2026-10-03", "2026-10-30", "2026-08-01", "2026-02-10"],
            "reportDate": ["2026-11-10", "2026-10-01", "2026-10-30", "2026-06-27", ""],
            "primaryDocument": ["xslF345X05/form4.xml", "xslF345X05/wk-form4.xml", "aapl-8k.htm",
                                "aapl-10q.htm", "sc13g.htm"],
            "items": ["", "", "2.02,9.01", "", ""],
        }},
    }
    facts = {"facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
                fact("2025-09-28", "2025-12-27", 100.0, "2026-01-30"),
                fact("2025-09-28", "2026-03-28", 180.0, "2026-05-01"),   # 6M YTD
                fact("2025-09-28", "2026-06-27", 270.0, "2026-08-01"),   # 9M YTD
                fact("2025-09-28", "2026-09-26", 400.0, "2026-10-30", "10-K"),  # FY
                fact("2024-09-29", "2025-09-27", 350.0, "2025-10-31", "10-K"),
            ]}},
            "NetIncomeLoss": {"units": {"USD": [
                fact("2025-09-28", "2025-12-27", 25.0, "2026-01-30"),
                fact("2025-12-28", "2026-03-28", 20.0, "2026-05-01"),
                fact("2026-03-29", "2026-06-27", 22.0, "2026-08-01"),
                fact("2025-09-28", "2026-09-26", 100.0, "2026-10-30", "10-K"),
            ]}},
            "EarningsPerShareDiluted": {"units": {"USD/shares": [
                fact("2025-09-28", "2025-12-27", 2.5, "2026-01-30"),
                fact("2025-12-28", "2026-03-28", 2.0, "2026-05-01"),
                fact("2026-03-29", "2026-06-27", 2.2, "2026-08-01"),
                fact("2025-09-28", "2026-09-26", 10.0, "2026-10-30", "10-K"),
            ]}},
            "StockholdersEquity": {"units": {"USD": [
                fact(None, "2026-09-26", 50.0, "2026-10-30", "10-K"),
                fact(None, "2026-06-27", 48.0, "2026-08-01"),
            ]}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            fact(None, "2026-10-17", 10.0, "2026-10-30", "10-K"),
        ]}}},
    }}
    header_13g = ("<pre>&lt;SEC-HEADER&gt;\nSUBJECT COMPANY:\n\tCOMPANY DATA:\n\t\t"
                  "COMPANY CONFORMED NAME:\t\t\tAPPLE INC\nFILED BY:\n\tCOMPANY DATA:\n\t\t"
                  "COMPANY CONFORMED NAME:\t\t\tVANGUARD GROUP INC\n</pre>")
    return {
        "https://www.sec.gov/files/company_tickers.json":
            {"0": {"cik_str": CIK, "ticker": "AAPL", "title": "Apple Inc."}},
        f"https://data.sec.gov/submissions/CIK{CIK:010d}.json": submissions,
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK:010d}.json": facts,
        f"{arch}/{nodash_buy}/form4.xml": BUY_FORM4,
        f"{arch}/{nodash_sell}/wk-form4.xml": fixture_text("form4.xml"),
        f"{arch}/000095010326000005/0000950103-26-000005-index-headers.html": header_13g,
    }


class FakeSec:
    """Replaces SecClient._get with canned responses; records every URL requested."""

    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.fail = False

    def __call__(self, url: str) -> httpx.Response:
        self.calls.append(url)
        if self.fail:
            raise httpx.ConnectError("boom")
        if url not in self.responses:
            raise NotFound(url)
        body = self.responses[url]
        req = httpx.Request("GET", url)
        if isinstance(body, str):
            return httpx.Response(200, text=body, request=req)
        return httpx.Response(200, content=json.dumps(body).encode(), request=req)


@pytest.fixture
def make_mi(tmp_path, monkeypatch):
    monkeypatch.delenv("MI_YAHOO_ENABLED", raising=False)

    def _make(yahoo_enabled: bool = False, responses: dict[str, Any] | None = None):
        mi = MarketIntel(cache_dir=str(tmp_path / "cache"), yahoo_enabled=yahoo_enabled,
                         sec_user_agent="market-intel-tests test@example.com", api_keys="")
        fake = FakeSec(responses if responses is not None else sec_responses())

        def _get(url: str) -> httpx.Response:
            # Run fake through the real error handling path.
            try:
                return fake(url)
            except httpx.HTTPError as exc:
                from market_intel.errors import UpstreamError
                raise UpstreamError(str(exc)) from exc

        monkeypatch.setattr(mi.sec, "_get", _get)
        return mi, fake

    return _make

from datetime import date

import pandas as pd
import pytest

from market_intel.parsers import xbrl
from market_intel.parsers.form4 import parse_form4, raw_xml_document
from market_intel.parsers.frames import pick, rows

from .conftest import fact, fixture_text, sec_responses


def test_raw_xml_document_strips_xsl_prefix():
    assert raw_xml_document("xslF345X05/wk-form4_1.xml") == "wk-form4_1.xml"
    assert raw_xml_document("form4.xml") == "form4.xml"


def test_parse_form4():
    txs = parse_form4(fixture_text("form4.xml"), accession="A", filing_date=date(2026, 10, 3), url="u")
    assert len(txs) == 3
    sale, tax, rsu = txs
    assert sale.insider_name == "COOK TIMOTHY D"
    assert sale.roles == ["Chief Executive Officer", "Director"]
    assert (sale.code, sale.shares, sale.price) == ("S", 1000.0, 250.5)
    assert sale.value == 250500.0
    assert sale.is_open_market and sale.is_10b5_1_plan and sale.direct_ownership
    assert sale.shares_owned_after == 3_280_000
    assert tax.code == "F" and not tax.is_open_market
    assert rsu.is_derivative and rsu.price is None and rsu.value is None


def test_quarterly_derives_from_ytd_and_standalone():
    facts = sec_responses()["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]
    rev = xbrl.quarterly(xbrl.collect(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax"], "USD"))
    assert {e.isoformat(): v for e, (_, v) in rev.items()} == {
        "2025-12-27": 100, "2026-03-28": 80, "2026-06-27": 90, "2026-09-26": 130,
    }
    ni = xbrl.quarterly(xbrl.collect(facts, ["NetIncomeLoss"], "USD"))
    assert ni[date(2026, 9, 26)] == (date(2026, 6, 28), 33.0)  # FY 100 − (25+20+22)


def test_collect_prefers_latest_filing_and_concept_priority():
    facts = {"facts": {"us-gaap": {
        "A": {"units": {"USD": [fact("2025-01-01", "2025-12-31", 1, "2026-02-01", "10-K"),
                                fact("2025-01-01", "2025-12-31", 2, "2027-02-01", "10-K")]}},
        "B": {"units": {"USD": [fact("2025-01-01", "2025-12-31", 9, "2026-02-01", "10-K"),
                                fact("2024-01-01", "2024-12-31", 7, "2025-02-01", "10-K")]}},
    }}}
    got = xbrl.annual(xbrl.collect(facts, ["A", "B"], "USD"))
    assert got[date(2025, 12, 31)].val == 2  # restated value wins, concept A beats B
    assert got[date(2024, 12, 31)].val == 7  # B fills the gap


def test_frames_rows_are_case_insensitive_and_nan_safe():
    df = pd.DataFrame({"upLast7days": [1], "downLast7Days": [float("nan")]}, index=["0q"])
    r = rows(df, "period")[0]
    assert r["period"] == "0q"
    assert pick(r, "uplast7days") == 1
    assert pick(r, "downLast7days") is None


@pytest.mark.parametrize("header,expected", [
    ("FILED BY:\n\tCOMPANY DATA:\n\t\tCOMPANY CONFORMED NAME:\t\tBLACKROCK INC.\n", "BLACKROCK INC."),
    ("&lt;FILED-BY&gt;\n&lt;COMPANY-DATA&gt;\n&lt;CONFORMED-NAME&gt;VANGUARD GROUP INC\n", "VANGUARD GROUP INC"),
    ("nothing useful", None),
])
def test_filer_name(header, expected):
    from market_intel.datasets.ownership import _filer_name
    assert _filer_name(header) == expected

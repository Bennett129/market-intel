"""Parse SEC Form 4 (statement of changes in beneficial ownership) XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from ..models import InsiderTransaction

CODE_DESCRIPTIONS = {
    "P": "Open market purchase",
    "S": "Open market sale",
    "A": "Grant / award",
    "D": "Disposition to issuer",
    "F": "Tax withholding",
    "I": "Discretionary transaction",
    "M": "Option exercise",
    "C": "Conversion of derivative",
    "E": "Expiration of short derivative",
    "H": "Expiration of long derivative",
    "O": "Exercise of out-of-the-money derivative",
    "X": "Exercise of in-the-money derivative",
    "G": "Gift",
    "L": "Small acquisition",
    "W": "Acquired/disposed by will or laws of descent",
    "Z": "Deposit into/withdrawal from voting trust",
    "J": "Other",
    "K": "Equity swap",
    "U": "Tender of shares in change of control",
}


@dataclass(frozen=True)
class Owner:
    name: str
    cik: str | None
    roles: tuple[str, ...]


def raw_xml_document(primary_document: str) -> str:
    """EDGAR's ``primaryDocument`` for Form 4 often points at the XSL-rendered view
    (``xslF345X05/form4.xml``). The raw XML has the same name without that prefix."""
    head, _, tail = primary_document.partition("/")
    return tail if tail and head.lower().startswith("xsl") else primary_document


def _text(el: ET.Element | None, path: str) -> str | None:
    """Read ``path`` and unwrap the ``<value>`` child that most Form 4 fields use."""
    if el is None:
        return None
    node = el.find(path)
    if node is None:
        return None
    value = node.find("value")
    raw = (value.text if value is not None else node.text) or ""
    raw = raw.strip()
    return raw or None


def _float(el: ET.Element | None, path: str) -> float | None:
    raw = _text(el, path)
    try:
        return float(raw.replace(",", "")) if raw else None
    except ValueError:
        return None


def _bool(el: ET.Element | None, path: str) -> bool:
    return (_text(el, path) or "").lower() in {"1", "true"}


def _date(el: ET.Element | None, path: str) -> date | None:
    raw = _text(el, path)
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def _owners(root: ET.Element) -> list[Owner]:
    owners: list[Owner] = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        roles: list[str] = []
        if _bool(rel, "isOfficer"):
            roles.append(_text(rel, "officerTitle") or "Officer")
        if _bool(rel, "isDirector"):
            roles.append("Director")
        if _bool(rel, "isTenPercentOwner"):
            roles.append("10% Owner")
        if _bool(rel, "isOther"):
            roles.append(_text(rel, "otherText") or "Other")
        owners.append(
            Owner(
                name=_text(ro, "reportingOwnerId/rptOwnerName") or "Unknown",
                cik=_text(ro, "reportingOwnerId/rptOwnerCik"),
                roles=tuple(roles),
            )
        )
    return owners


def parse_form4(xml_text: str, *, accession: str, filing_date: date, url: str) -> list[InsiderTransaction]:
    root = ET.fromstring(xml_text.strip().encode("utf-8"))
    owners = _owners(root)
    if not owners:
        return []
    primary = owners[0]
    name = "; ".join(o.name for o in owners) if len(owners) > 1 else primary.name
    roles = sorted({r for o in owners for r in o.roles})
    plan = _bool(root, "aff10b5One")

    out: list[InsiderTransaction] = []
    tables = (("nonDerivativeTable/nonDerivativeTransaction", False),
              ("derivativeTable/derivativeTransaction", True))
    for path, derivative in tables:
        for tx in root.findall(path):
            code = _text(tx, "transactionCoding/transactionCode")
            shares = _float(tx, "transactionAmounts/transactionShares")
            price = _float(tx, "transactionAmounts/transactionPricePerShare")
            ad = _text(tx, "transactionAmounts/transactionAcquiredDisposedCode")
            ownership = _text(tx, "ownershipNature/directOrIndirectOwnership")
            out.append(
                InsiderTransaction(
                    filing_date=filing_date,
                    transaction_date=_date(tx, "transactionDate"),
                    insider_name=name,
                    insider_cik=primary.cik,
                    roles=roles,
                    security=_text(tx, "securityTitle"),
                    code=code,
                    code_description=CODE_DESCRIPTIONS.get(code or ""),
                    acquired_disposed=ad if ad in ("A", "D") else None,
                    shares=shares,
                    price=price,
                    value=round(shares * price, 2) if shares is not None and price else None,
                    shares_owned_after=_float(
                        tx, "postTransactionAmounts/sharesOwnedFollowingTransaction"
                    ),
                    direct_ownership=None if ownership is None else ownership == "D",
                    is_derivative=derivative,
                    is_open_market=not derivative and code in ("P", "S"),
                    is_10b5_1_plan=plan,
                    accession=accession,
                    url=url,
                )
            )
    return out

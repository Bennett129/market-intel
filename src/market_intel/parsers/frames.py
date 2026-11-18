"""Helpers for turning yfinance DataFrames into plain rows. yfinance column names shift between
versions (e.g. ``downLast7Days`` vs ``upLast7days``), so lookups are case-insensitive and tolerant."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd


def _key(name: Any) -> str:
    return str(name).replace(" ", "").replace("_", "").lower()


def rows(df: Any, index_name: str = "index") -> list[dict[str, Any]]:
    """DataFrame → list of dicts with normalised keys; the index is exposed as ``index_name``."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out = []
    for idx, rec in zip(df.index, df.to_dict("records"), strict=False):
        row = {_key(k): clean(v) for k, v in rec.items()}
        row[_key(index_name)] = clean(idx)
        out.append(row)
    return out


def pick(row: dict[str, Any], *names: str) -> Any:
    for n in names:
        v = row.get(_key(n))
        if v is not None:
            return v
    return None


def clean(v: Any) -> Any:
    """NaN/NaT → None; numpy scalars → Python; Timestamps → datetime."""
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.to_pydatetime()
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):
        try:
            v = v.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def num(v: Any) -> float | None:
    v = clean(v)
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def integer(v: Any) -> int | None:
    f = num(v)
    return None if f is None else int(f)


def as_date(v: Any) -> date | None:
    v = clean(v)
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None

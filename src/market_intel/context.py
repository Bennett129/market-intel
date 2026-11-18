"""Collects provenance (sources, freshness, warnings) while a dataset is being built, so every
response can say where its data came from and whether any of it was served stale."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FetchMeta:
    sources: set[str] = field(default_factory=set)
    stale: bool = False
    oldest_fetch: float | None = None
    warnings: list[str] = field(default_factory=list)

    def record(self, source: str, fetched_at: float, stale: bool) -> None:
        self.sources.add(source)
        self.stale |= stale
        if self.oldest_fetch is None or fetched_at < self.oldest_fetch:
            self.oldest_fetch = fetched_at

    @property
    def fetched_at(self) -> datetime | None:
        if self.oldest_fetch is None:
            return None
        return datetime.fromtimestamp(self.oldest_fetch, tz=UTC)


_current: ContextVar[FetchMeta | None] = ContextVar("market_intel_fetch_meta", default=None)


@contextmanager
def collect() -> Iterator[FetchMeta]:
    meta = FetchMeta()
    token = _current.set(meta)
    try:
        yield meta
    finally:
        _current.reset(token)


def record(source: str, fetched_at: float, stale: bool) -> None:
    if (meta := _current.get()) is not None:
        meta.record(source, fetched_at, stale)


def warn(message: str) -> None:
    if (meta := _current.get()) is not None and message not in meta.warnings:
        meta.warnings.append(message)

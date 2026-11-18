"""Disk cache for raw upstream responses.

Raw responses are cached instead of normalised models, so changing a model or parser never
needs a cache flush. Entries are never deleted when their TTL passes; an expired entry is the
fallback if the upstream call fails (served with ``stale=True``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

import diskcache

from . import context
from .errors import DatasetUnavailable, NotFound, UpstreamError

T = TypeVar("T")

# TTLs in seconds. ``None`` means immutable (e.g. a filed SEC document never changes).
TTL_MINUTE = 60
TTL_HOUR = 3600
TTL_DAY = 86400


class Cache:
    def __init__(self, directory: str, size_limit: int = 2**30) -> None:
        self._dc = diskcache.Cache(directory, size_limit=size_limit)

    def get_or_fetch(self, key: str, ttl: float | None, fetch: Callable[[], T], source: str) -> T:
        entry: dict[str, Any] | None = self._dc.get(key)
        now = time.time()
        if entry is not None and (ttl is None or now - entry["t"] < ttl):
            context.record(source, entry["t"], stale=False)
            return entry["v"]
        try:
            value = fetch()
        except (NotFound, DatasetUnavailable):
            raise
        except Exception as exc:
            if entry is not None:
                context.record(source, entry["t"], stale=True)
                context.warn(f"{source}: upstream failed ({type(exc).__name__}); serving cached data")
                return entry["v"]
            if isinstance(exc, UpstreamError):
                raise
            raise UpstreamError(f"{source}: {type(exc).__name__}: {exc}") from exc
        self._dc.set(key, {"v": value, "t": now})
        context.record(source, now, stale=False)
        return value

    def clear(self) -> None:
        self._dc.clear()

    def close(self) -> None:
        self._dc.close()

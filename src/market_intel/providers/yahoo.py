"""Yahoo Finance via yfinance: unofficial, so it's behind a kill switch.

With ``MI_YAHOO_ENABLED=false``:
- ``yfinance`` is never imported and no request is ever sent to Yahoo.
- :meth:`YahooClient.get` raises :class:`DatasetUnavailable` (Yahoo-only datasets → HTTP 503).
- :meth:`YahooClient.optional` returns ``None`` with a warning (mixed datasets degrade).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .. import context
from ..cache import Cache
from ..config import Settings
from ..errors import DatasetUnavailable, MarketIntelError
from ..ratelimit import CircuitBreaker, RateLimiter
from .sec import normalize_symbol

SOURCE = "yahoo_finance"
T = TypeVar("T")


class YahooClient:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self._settings = settings
        self._cache = cache
        self._limiter = RateLimiter(settings.yahoo_max_rps)
        self._breaker = CircuitBreaker(
            SOURCE, settings.breaker_threshold, settings.breaker_cooldown_s
        )

    @property
    def enabled(self) -> bool:
        return self._settings.yahoo_enabled

    @property
    def circuit_open(self) -> bool:
        return self._breaker.is_open

    def get(self, symbol: str, name: str, ttl: float, call: Callable[[Any], T]) -> T:
        """Fetch ``call(yf.Ticker(symbol))`` through the cache. Raises if Yahoo is disabled."""
        if not self.enabled:
            raise DatasetUnavailable(
                f"'{name}' requires Yahoo Finance, which is disabled (MI_YAHOO_ENABLED=false)"
            )
        sym = normalize_symbol(symbol)

        def fetch() -> T:
            import yfinance as yf  # imported lazily so a disabled Yahoo is never touched

            self._breaker.before()
            self._limiter.acquire()
            try:
                value = call(yf.Ticker(sym))
            except Exception:
                self._breaker.failure()
                raise
            self._breaker.success()
            return value

        return self._cache.get_or_fetch(f"yahoo:{name}:{sym}", ttl, fetch, SOURCE)

    def optional(self, symbol: str, name: str, ttl: float, call: Callable[[Any], T]) -> T | None:
        """Like :meth:`get`, but returns ``None`` (plus a warning) instead of raising.
        Used for Yahoo *enrichment* of datasets whose primary source is EDGAR."""
        if not self.enabled:
            context.warn(f"yahoo disabled: {name} omitted")
            return None
        try:
            return self.get(symbol, name, ttl, call)
        except MarketIntelError as exc:
            context.warn(f"yahoo {name} unavailable: {exc}")
            return None

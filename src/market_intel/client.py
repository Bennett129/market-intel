"""Library facade: ``MarketIntel`` is all a bot or notebook needs; no HTTP server required.

    from market_intel import MarketIntel
    mi = MarketIntel(sec_user_agent="my-bot me@example.com", yahoo_enabled=False)
    mi.insiders("NVDA").summary
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from . import context
from .cache import Cache
from .config import Settings
from .datasets.analysts import build_analysts
from .datasets.corporate_actions import build_corporate_actions
from .datasets.estimates import build_estimates
from .datasets.events import build_events
from .datasets.fundamentals import build_fundamentals
from .datasets.insiders import build_insiders
from .datasets.ownership import build_ownership
from .datasets.profile import build_profile
from .models import (
    Analysts,
    CorporateActions,
    Dataset,
    Estimates,
    Events,
    Fundamentals,
    InsiderActivity,
    Meta,
    Ownership,
    Profile,
)
from .providers import SecClient, YahooClient

D = TypeVar("D", bound=Dataset)


class MarketIntel:
    def __init__(self, settings: Settings | None = None, **overrides: Any) -> None:
        self.settings = settings.model_copy(update=overrides) if settings else Settings(**overrides)
        self.cache = Cache(self.settings.cache_dir)
        self.sec = SecClient(self.settings, self.cache)
        self.yahoo = YahooClient(self.settings, self.cache)

    def _run(self, build: Callable[[], D]) -> D:
        with context.collect() as meta:
            result = build()
        result.meta = Meta(
            sources=sorted(meta.sources), fetched_at=meta.fetched_at, stale=meta.stale,
            warnings=meta.warnings, yahoo_enabled=self.yahoo.enabled,
        )
        return result

    # -- datasets --------------------------------------------------------------------------

    def profile(self, symbol: str) -> Profile:
        return self._run(lambda: build_profile(self.sec, self.yahoo, symbol))

    def fundamentals(self, symbol: str, price: float | None = None) -> Fundamentals:
        return self._run(lambda: build_fundamentals(self.sec, self.yahoo, symbol, price))

    def insiders(self, symbol: str, limit: int = 40, days: int = 365) -> InsiderActivity:
        return self._run(lambda: build_insiders(self.sec, symbol, limit, days))

    def ownership(self, symbol: str) -> Ownership:
        return self._run(lambda: build_ownership(self.sec, self.yahoo, symbol))

    def analysts(self, symbol: str) -> Analysts:
        return self._run(lambda: build_analysts(self.yahoo, symbol))

    def estimates(self, symbol: str) -> Estimates:
        return self._run(lambda: build_estimates(self.yahoo, symbol))

    def events(self, symbol: str, start: date | None = None, end: date | None = None) -> Events:
        return self._run(lambda: build_events(self.sec, self.yahoo, symbol, start, end))

    def corporate_actions(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> CorporateActions:
        return self._run(lambda: build_corporate_actions(self.yahoo, symbol, start, end))

    # -- status ----------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "providers": {
                "sec_edgar": {"enabled": True,
                              "configured": bool(self.settings.sec_user_agent.strip())},
                "yahoo_finance": {"enabled": self.yahoo.enabled,
                                  "circuit_open": self.yahoo.circuit_open},
            },
            "datasets": {
                "profile": "sec_edgar (+yahoo enrichment)",
                "fundamentals": "sec_edgar (+yahoo price for ratios, or pass ?price=)",
                "insiders": "sec_edgar",
                "ownership": "sec_edgar (+yahoo institutional holders)",
                "events": "sec_edgar (+yahoo earnings/dividend calendar)",
                "analysts": "yahoo" if self.yahoo.enabled else "unavailable (yahoo disabled)",
                "estimates": "yahoo" if self.yahoo.enabled else "unavailable (yahoo disabled)",
                "corporate_actions": "yahoo" if self.yahoo.enabled else "unavailable (yahoo disabled)",
            },
        }

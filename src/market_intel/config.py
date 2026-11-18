"""Runtime configuration. Every setting can be overridden with an ``MI_``-prefixed env var or a
``.env`` file, or passed directly to :class:`market_intel.MarketIntel`."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MI_", env_file=".env", extra="ignore")

    # --- Providers -------------------------------------------------------------------------
    # Master switch for Yahoo Finance. When false, yfinance is never imported or called:
    # Yahoo-only datasets return `dataset_unavailable` and mixed datasets return EDGAR data only.
    yahoo_enabled: bool = True

    # SEC requires a descriptive User-Agent with contact details, e.g. "MyApp me@example.com".
    # https://www.sec.gov/os/webmaster-faq#developers
    sec_user_agent: str = ""

    # --- Limits ----------------------------------------------------------------------------
    sec_max_rps: float = 8.0  # SEC fair-access limit is 10 req/s
    yahoo_max_rps: float = 2.0
    breaker_threshold: int = 5  # consecutive failures before a provider is paused
    breaker_cooldown_s: float = 60.0

    # --- Storage / API ---------------------------------------------------------------------
    cache_dir: str = ".cache/market-intel"
    api_keys: str = ""  # comma-separated; empty disables auth (local dev only)

    @property
    def api_key_set(self) -> frozenset[str]:
        return frozenset(k.strip() for k in self.api_keys.split(",") if k.strip())

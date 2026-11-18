from __future__ import annotations


class MarketIntelError(Exception):
    code = "error"
    status = 500


class NotFound(MarketIntelError):
    code = "not_found"
    status = 404


class SymbolNotFound(NotFound):
    code = "symbol_not_found"


class DatasetUnavailable(MarketIntelError):
    """The dataset needs a provider that is disabled (e.g. Yahoo with MI_YAHOO_ENABLED=false)."""

    code = "dataset_unavailable"
    status = 503


class UpstreamError(MarketIntelError):
    code = "upstream_error"
    status = 502


class ConfigError(MarketIntelError):
    code = "config_error"
    status = 500

__version__ = "0.1.0"

from .client import MarketIntel
from .config import Settings
from .errors import (
    ConfigError,
    DatasetUnavailable,
    MarketIntelError,
    NotFound,
    SymbolNotFound,
    UpstreamError,
)

__all__ = [
    "ConfigError",
    "DatasetUnavailable",
    "MarketIntel",
    "MarketIntelError",
    "NotFound",
    "Settings",
    "SymbolNotFound",
    "UpstreamError",
    "__version__",
]

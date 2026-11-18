"""Pure price-based technicals (no I/O). Consumers can pass their own bars, so the results are
the same whether the prices came from Alpaca, Yahoo or a backtest."""

from .levels import Bar, compute_levels

__all__ = ["Bar", "compute_levels"]

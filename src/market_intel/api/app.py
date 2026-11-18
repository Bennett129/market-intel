"""HTTP API: a thin layer over :class:`MarketIntel`. Run with ``mi serve`` or
``uvicorn --factory market_intel.api.app:create_app``."""

from __future__ import annotations

import logging
import secrets
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..client import MarketIntel
from ..errors import MarketIntelError
from ..models import (
    Analysts,
    CorporateActions,
    Estimates,
    Events,
    Fundamentals,
    InsiderActivity,
    Levels,
    LevelsRequest,
    Ownership,
    Profile,
)
from ..technicals import Bar

log = logging.getLogger("market_intel")

Symbol = Annotated[str, Path(pattern=r"^[A-Za-z0-9.\-^=]{1,15}$", description="Ticker, e.g. AAPL")]


def create_app(mi: MarketIntel | None = None) -> FastAPI:
    mi = mi or MarketIntel()
    keys = mi.settings.api_key_set
    if not keys:
        log.warning("MI_API_KEYS is empty: API authentication is DISABLED (dev mode)")

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if keys and not any(secrets.compare_digest(x_api_key or "", k) for k in keys):
            raise HTTPException(401, detail={"error": "unauthorized", "message": "Invalid X-API-Key"})

    app = FastAPI(title="market-intel", version=__version__,
                  description="SEC EDGAR + optional Yahoo Finance market intelligence.")

    @app.exception_handler(MarketIntelError)
    async def _handle(_: Request, exc: MarketIntelError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": str(exc)})

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__, **mi.status()}

    deps = [Depends(require_key)]

    @app.get("/v1/tickers/{symbol}/profile", response_model=Profile, dependencies=deps, tags=["tickers"])
    def profile(symbol: Symbol) -> Profile:
        return mi.profile(symbol)

    @app.get("/v1/tickers/{symbol}/fundamentals", response_model=Fundamentals, dependencies=deps,
             tags=["tickers"])
    def fundamentals(
        symbol: Symbol,
        price: Annotated[float | None, Query(gt=0, description="Price for valuation ratios")] = None,
    ) -> Fundamentals:
        return mi.fundamentals(symbol, price)

    @app.get("/v1/tickers/{symbol}/insiders", response_model=InsiderActivity, dependencies=deps,
             tags=["tickers"])
    def insiders(
        symbol: Symbol,
        limit: Annotated[int, Query(ge=1, le=200)] = 40,
        days: Annotated[int, Query(ge=1, le=1095)] = 365,
    ) -> InsiderActivity:
        return mi.insiders(symbol, limit, days)

    @app.get("/v1/tickers/{symbol}/ownership", response_model=Ownership, dependencies=deps,
             tags=["tickers"])
    def ownership(symbol: Symbol) -> Ownership:
        return mi.ownership(symbol)

    @app.get("/v1/tickers/{symbol}/analysts", response_model=Analysts, dependencies=deps,
             tags=["tickers"])
    def analysts(symbol: Symbol) -> Analysts:
        return mi.analysts(symbol)

    @app.get("/v1/tickers/{symbol}/estimates", response_model=Estimates, dependencies=deps,
             tags=["tickers"])
    def estimates(symbol: Symbol) -> Estimates:
        return mi.estimates(symbol)

    @app.get("/v1/tickers/{symbol}/events", response_model=Events, dependencies=deps,
             tags=["tickers"])
    def events(symbol: Symbol, start: date | None = None, end: date | None = None) -> Events:
        return mi.events(symbol, start, end)

    @app.get("/v1/tickers/{symbol}/corporate-actions", response_model=CorporateActions,
             dependencies=deps, tags=["tickers"])
    def corporate_actions(
        symbol: Symbol, start: date | None = None, end: date | None = None
    ) -> CorporateActions:
        return mi.corporate_actions(symbol, start, end)

    @app.get("/v1/tickers/{symbol}/levels", response_model=Levels, dependencies=deps,
             tags=["technicals"])
    def levels(
        symbol: Symbol,
        max_levels: Annotated[int, Query(ge=1, le=20)] = 6,
    ) -> Levels:
        """Levels from one year of Yahoo daily history (503 when Yahoo is disabled)."""
        return mi.levels(symbol, max_levels=max_levels)

    @app.post("/v1/technicals/levels", response_model=Levels, dependencies=deps,
              tags=["technicals"])
    def levels_from_bars(req: LevelsRequest) -> Levels:
        """Levels and a trend channel from bars you supply (e.g. your own Alpaca daily bars).
        No upstream call is made, so this works with Yahoo switched off."""
        bars = [Bar(t=b.t, o=b.o, h=b.h, l=b.l, c=b.c, v=b.v) for b in req.bars]
        return mi.levels(req.symbol, bars, window=req.window, max_levels=req.max_levels,
                         channel_bars=req.channel_bars)

    return app

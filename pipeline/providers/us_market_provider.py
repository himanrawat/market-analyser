"""US-only runtime provider wrapper.

This keeps all FMP-backed logic explicitly scoped to the US lane so the India
path does not accidentally pick it up again.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger

from pipeline.db.enums import Country
from pipeline.providers.dto import (
    AnalystForecastSnapshot,
    EventRecord,
    FundamentalSnapshot,
    NewsArticle,
    StockProfile,
)
from pipeline.providers.errors import (
    DataProviderError,
    MissingApiKeyError,
    PlanLimitError,
    SymbolNotFoundError,
)
from pipeline.providers.fmp_provider import FMPProvider
from pipeline.providers.yfinance_provider import YFinanceProvider

PROVIDER_NAME = "us_market"


class USMarketProvider:
    """US lane wrapper: FMP primary with yfinance fallback where appropriate."""

    def __init__(
        self,
        *,
        fmp: FMPProvider | None = None,
        yf: YFinanceProvider | None = None,
    ) -> None:
        self._fmp = fmp or FMPProvider()
        self._yf = yf or YFinanceProvider()

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        self._ensure_us(country, ticker)
        try:
            return self._fmp.get_profile(ticker, country)
        except MissingApiKeyError:
            logger.warning("FMP API key not configured — falling back to yfinance for US profile")
        except (PlanLimitError, SymbolNotFoundError):
            logger.debug(f"FMP profile unavailable for {ticker} — falling back to yfinance")
        return self._yf.get_profile(ticker, country)

    def get_quarterly_fundamentals(
        self,
        ticker: str,
        country: Country,
        limit: int = 20,
    ) -> list[FundamentalSnapshot]:
        self._ensure_us(country, ticker)
        try:
            return self._fmp.get_quarterly_fundamentals(ticker, country, limit)
        except MissingApiKeyError:
            logger.warning("FMP API key not configured — falling back to yfinance for US fundamentals")
        except (PlanLimitError, SymbolNotFoundError):
            logger.debug(f"FMP fundamentals unavailable for {ticker} — falling back to yfinance")
        return self._yf.get_quarterly_fundamentals(ticker, country, limit)

    def get_stock_news(
        self,
        ticker: str,
        country: Country,
        since: datetime,
        limit: int = 50,
    ) -> list[NewsArticle]:
        self._ensure_us(country, ticker)
        try:
            return self._fmp.get_stock_news(ticker, country, since, limit)
        except (MissingApiKeyError, PlanLimitError, SymbolNotFoundError):
            return []

    def get_upcoming_events(
        self,
        ticker: str,
        country: Country,
        within_days: int = 30,
    ) -> list[EventRecord]:
        self._ensure_us(country, ticker)
        try:
            return self._fmp.get_upcoming_events(ticker, country, within_days)
        except (MissingApiKeyError, PlanLimitError, SymbolNotFoundError):
            return []

    def get_analyst_forecast(
        self,
        ticker: str,
        country: Country,
        *,
        limit: int = 4,
        current_price: float | None = None,
    ) -> AnalystForecastSnapshot | None:
        self._ensure_us(country, ticker)
        return self._fmp.get_analyst_forecast(
            ticker,
            country,
            limit=limit,
            current_price=current_price,
        )

    def get_stock_peers(
        self,
        ticker: str,
        country: Country,
        *,
        limit: int = 8,
    ) -> list[str]:
        self._ensure_us(country, ticker)
        return self._fmp.get_stock_peers(ticker, country, limit=limit)

    @staticmethod
    def _ensure_us(country: Country, ticker: str) -> None:
        if country != Country.US:
            raise DataProviderError(
                f"{PROVIDER_NAME} is US-only and cannot be used for '{ticker}' in {country}."
            )

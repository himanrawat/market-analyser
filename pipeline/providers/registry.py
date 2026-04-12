"""DataProvider facade — the single entry point for all data fetching.

Usage (anywhere in the pipeline):

    from pipeline.providers import get_data_provider
    dp = get_data_provider()

    bars = dp.prices.get_daily_ohlcv("RELIANCE", Country.INDIA, start, end)
    fundamentals = dp.fundamentals.get_quarterly_fundamentals("AAPL", Country.US)
    macro = dp.macro.get_series("FEDFUNDS", start, end)

The facade is constructed once per process (singleton via `get_data_provider()`).
Each concrete provider is instantiated with its own `JsonCache`, so cache files
are namespaced by provider name under `data/cache/<provider>/`.

Provider routing:
- prices     → YFinanceProvider (free, reliable)
- fundamentals → FMPProvider primary, YFinanceProvider fallback
- news       → FMPProvider (stock stream) + NewsAPIProvider (general backup)
- events     → FMPProvider
- macro      → FREDProvider (US) + RBIProvider (India) + YFinanceProvider (VIX/FX/indices)
- universe   → handled by the universe module (scrapes Wikipedia / uses yfinance screener)
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from loguru import logger

from pipeline.db.enums import Country
from pipeline.providers.dto import (
    EventRecord,
    FundamentalSnapshot,
    MacroReading,
    NewsArticle,
    PriceBar,
    StockProfile,
)
from pipeline.providers.errors import DataProviderError, MissingApiKeyError, PlanLimitError
from pipeline.providers.errors import SymbolNotFoundError
from pipeline.providers.fmp_provider import FMPProvider
from pipeline.providers.fred_provider import FREDProvider
from pipeline.providers.newsapi_provider import NewsAPIProvider
from pipeline.providers.rbi_provider import RBIProvider
from pipeline.providers.yfinance_provider import YFinanceProvider

# yfinance indicator keys that correspond to macro series
_YF_MACRO_INDICATORS = {
    "INDIA_VIX", "US_VIX", "USD_INR",
    "NIFTY_50", "SP_500", "NASDAQ", "SENSEX",
    "BRENT_OIL", "GOLD", "US_10Y",
}

# FRED indicators
_FRED_INDICATORS = {
    "FEDFUNDS", "US_CPI_YOY", "US_GDP_GROWTH", "US_UNEMPLOYMENT",
}

# RBI indicators
_RBI_INDICATORS = {
    "INDIA_REPO_RATE", "INDIA_CPI_YOY",
}


class _PriceService:
    """Thin wrapper over YFinanceProvider (prices are always from yfinance)."""

    def __init__(self, yf: YFinanceProvider) -> None:
        self._yf = yf

    def get_daily_ohlcv(
        self, ticker: str, country: Country, start: date, end: date
    ) -> list[PriceBar]:
        return self._yf.get_daily_ohlcv(ticker, country, start, end)

    def get_latest_quote(self, ticker: str, country: Country) -> PriceBar:
        return self._yf.get_latest_quote(ticker, country)


class _FundamentalService:
    """FMP primary, yfinance fallback on key missing or plan limit (e.g. Indian stocks)."""

    def __init__(self, fmp: FMPProvider, yf: YFinanceProvider) -> None:
        self._fmp = fmp
        self._yf = yf

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        try:
            return self._fmp.get_quarterly_fundamentals(ticker, country, limit)
        except (MissingApiKeyError, SymbolNotFoundError):
            logger.warning("FMP key missing — falling back to yfinance for fundamentals")
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)
        except PlanLimitError:
            logger.debug(f"FMP plan limit for {ticker} fundamentals — falling back to yfinance")
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        try:
            return self._fmp.get_profile(ticker, country)
        except (MissingApiKeyError, SymbolNotFoundError):
            logger.warning("FMP key missing — falling back to yfinance for profile")
            return self._yf.get_profile(ticker, country)
        except PlanLimitError:
            logger.debug(f"FMP plan limit for {ticker} profile — falling back to yfinance")
            return self._yf.get_profile(ticker, country)


class _NewsService:
    """FMP for stock-specific news, NewsAPI as general backup."""

    def __init__(self, fmp: FMPProvider, newsapi: NewsAPIProvider) -> None:
        self._fmp = fmp
        self._newsapi = newsapi

    def get_stock_news(
        self, ticker: str, country: Country, since: datetime
    ) -> list[NewsArticle]:
        try:
            return self._fmp.get_stock_news(ticker, country, since)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug(f"FMP stock news unavailable for {ticker} — skipping")
            return []

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]:
        """Try FMP first; fall back to NewsAPI on missing key or plan limit."""
        articles: list[NewsArticle] = []
        try:
            articles = self._fmp.get_general_news(since, limit)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug("FMP general news unavailable — trying NewsAPI")

        if not articles:
            try:
                articles = self._newsapi.get_general_news(since, limit)
            except MissingApiKeyError:
                logger.warning("Both FMP and NewsAPI keys missing — no general news")
        return articles


class _EventService:
    def __init__(self, fmp: FMPProvider) -> None:
        self._fmp = fmp

    def get_upcoming_events(
        self, ticker: str, country: Country, within_days: int = 30
    ) -> list[EventRecord]:
        try:
            return self._fmp.get_upcoming_events(ticker, country, within_days)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug(f"FMP events unavailable for {ticker} — skipping")
            return []


class _MacroService:
    """Routes by indicator name to FRED, RBI, or yfinance."""

    def __init__(self, fred: FREDProvider, rbi: RBIProvider, yf: YFinanceProvider) -> None:
        self._fred = fred
        self._rbi = rbi
        self._yf = yf

    def get_series(self, indicator: str, start: date, end: date) -> list[MacroReading]:
        if indicator in _YF_MACRO_INDICATORS:
            return self._yf.get_series(indicator, start, end)
        if indicator in _FRED_INDICATORS:
            try:
                return self._fred.get_series(indicator, start, end)
            except MissingApiKeyError:
                logger.warning(f"FRED key missing — no data for {indicator}")
                return []
        if indicator in _RBI_INDICATORS:
            return self._rbi.get_series(indicator, start, end)
        raise ValueError(
            f"Unknown macro indicator '{indicator}'. "
            f"Valid: {sorted(_YF_MACRO_INDICATORS | _FRED_INDICATORS | _RBI_INDICATORS)}"
        )


class DataProvider:
    """Composed facade over all data sources. Use `get_data_provider()` to
    get the singleton instance — don't construct this directly in pipeline code."""

    def __init__(
        self,
        yf: YFinanceProvider | None = None,
        fmp: FMPProvider | None = None,
        fred: FREDProvider | None = None,
        rbi: RBIProvider | None = None,
        newsapi: NewsAPIProvider | None = None,
    ) -> None:
        _yf = yf or YFinanceProvider()
        _fmp = fmp or FMPProvider()
        _fred = fred or FREDProvider()
        _rbi = rbi or RBIProvider()
        _newsapi = newsapi or NewsAPIProvider()

        self.prices = _PriceService(_yf)
        self.fundamentals = _FundamentalService(_fmp, _yf)
        self.news = _NewsService(_fmp, _newsapi)
        self.events = _EventService(_fmp)
        self.macro = _MacroService(_fred, _rbi, _yf)

    def health_check(self) -> dict[str, bool]:
        """Quick check of which providers are configured (key present + reachable).
        Used by `pipeline.cli check-providers`."""
        from pipeline.config import settings
        return {
            "yfinance": True,  # always available, no key needed
            "fmp": bool(settings.fmp_api_key),
            "fred": bool(settings.fred_api_key),
            "newsapi": bool(settings.newsapi_key),
            "rbi": True,  # scraper, no key needed
        }


@lru_cache(maxsize=1)
def get_data_provider() -> DataProvider:
    """Singleton factory. The same instance is reused across the pipeline run."""
    dp = DataProvider()
    health = dp.health_check()
    configured = [k for k, v in health.items() if v]
    missing = [k for k, v in health.items() if not v]
    logger.info(f"DataProvider ready. Configured: {configured}. Missing keys: {missing}")
    return dp

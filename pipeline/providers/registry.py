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
- prices       → YFinanceProvider (free, reliable, all markets)
- fundamentals → India: IndiaOfficialFundamentalsProvider (official NSE/BSE) → YFinanceProvider enrichment
               → US:    FMPProvider primary → YFinanceProvider fallback
- profile      → India: YFinanceProvider
               → US:    FMPProvider primary → YFinanceProvider fallback
- news         → India stock news: skipped (no reliable free source)
               → US stock news:    FMPProvider
               → general:          NewsAPIProvider primary → FMPProvider fallback
- events       → India: skipped (no reliable free source)
               → US:    FMPProvider
- macro        → FREDProvider (US, incl. VIXCLS) + RBIProvider (India) + YFinanceProvider (indices/FX)
- universe     → handled by the universe module
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
from pipeline.providers.india_official_provider import IndiaOfficialFundamentalsProvider
from pipeline.providers.newsapi_provider import NewsAPIProvider
from pipeline.providers.rbi_provider import RBIProvider
from pipeline.providers.yfinance_provider import YFinanceProvider

# yfinance indicator keys that correspond to macro series
_YF_MACRO_INDICATORS = {
    "INDIA_VIX", "USD_INR",
    "NIFTY_50", "SP_500", "NASDAQ", "SENSEX",
    "BRENT_OIL", "GOLD", "US_10Y",
}

# FRED indicators
_FRED_INDICATORS = {
    "FEDFUNDS", "US_CPI_YOY", "US_GDP_GROWTH", "US_UNEMPLOYMENT", "US_VIX",
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
    """Hybrid routing for fundamentals.

    India: official NSE/BSE first, yfinance enrichment/fallback. FMP not used.
    US: FMP primary, yfinance fallback.
    """

    def __init__(
        self,
        india_official: IndiaOfficialFundamentalsProvider,
        fmp: FMPProvider,
        yf: YFinanceProvider,
    ) -> None:
        self._india = india_official
        self._fmp = fmp
        self._yf = yf

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        official: list[FundamentalSnapshot] = []
        if country == Country.INDIA:
            try:
                official = self._india.get_quarterly_fundamentals(ticker, country, limit)
            except SymbolNotFoundError:
                logger.debug(f"Official India fundamentals unavailable for {ticker} — trying vendor lane")
            except DataProviderError as exc:
                logger.warning(
                    f"Official India fundamentals issue for {ticker}: {exc}. Falling back to vendor lane."
                )

        if official:
            if country == Country.INDIA and not _needs_vendor_enrichment(official):
                logger.debug(
                    f"Official India fundamentals already complete for {ticker} — skipping vendor enrichment"
                )
                return official[:limit]
            try:
                vendor = self._get_vendor_fundamentals(
                    ticker,
                    country,
                    limit,
                    silent=country == Country.INDIA,
                )
            except Exception:  # noqa: BLE001
                vendor = []
            return _merge_fundamental_snapshots(official, vendor, limit)

        return self._get_vendor_fundamentals(ticker, country, limit)

    def _get_vendor_fundamentals(
        self,
        ticker: str,
        country: Country,
        limit: int,
        *,
        silent: bool = False,
    ) -> list[FundamentalSnapshot]:
        # India: skip FMP entirely — use yfinance as the vendor lane
        if country == Country.INDIA:
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)

        try:
            return self._fmp.get_quarterly_fundamentals(ticker, country, limit)
        except MissingApiKeyError:
            if not silent:
                logger.warning("FMP API key not configured — falling back to yfinance for fundamentals")
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)
        except SymbolNotFoundError:
            if not silent:
                logger.debug(f"FMP symbol not found for {ticker} fundamentals — falling back to yfinance")
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)
        except PlanLimitError:
            if not silent:
                logger.debug(f"FMP plan limit for {ticker} fundamentals — falling back to yfinance")
            return self._yf.get_quarterly_fundamentals(ticker, country, limit)

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        # India: skip FMP — yfinance profile is sufficient
        if country == Country.INDIA:
            return self._yf.get_profile(ticker, country)

        try:
            return self._fmp.get_profile(ticker, country)
        except MissingApiKeyError:
            logger.warning("FMP API key not configured — falling back to yfinance for profile")
            return self._yf.get_profile(ticker, country)
        except SymbolNotFoundError:
            logger.debug(f"FMP symbol not found for {ticker} profile — falling back to yfinance")
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
        # India: FMP stock-specific news is sparse; skip it
        if country == Country.INDIA:
            return []
        try:
            return self._fmp.get_stock_news(ticker, country, since)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug(f"FMP stock news unavailable for {ticker} — skipping")
            return []

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]:
        """FMP general + FMP articles + stock-latest combined; NewsAPI as fallback."""
        articles: list[NewsArticle] = []

        # Try FMP sources first (general-latest + fmp-articles + stock-latest)
        try:
            articles += self._fmp.get_general_news(since, limit)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug("FMP general news unavailable — skipping")

        try:
            articles += self._fmp.get_fmp_articles(since, 20)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug("FMP articles unavailable — skipping")

        try:
            articles += self._fmp.get_stock_news_latest(since, 50)
        except (MissingApiKeyError, PlanLimitError):
            logger.debug("FMP stock-latest unavailable — skipping")

        # Deduplicate by URL
        seen: set[str] = set()
        deduped: list[NewsArticle] = []
        for a in articles:
            if a.url not in seen:
                seen.add(a.url)
                deduped.append(a)

        if deduped:
            return deduped[:limit]

        # NewsAPI as last resort
        try:
            return self._newsapi.get_general_news(since, limit)
        except MissingApiKeyError:
            logger.warning("FMP and NewsAPI both unavailable — no general news")
            return []


class _EventService:
    def __init__(self, fmp: FMPProvider) -> None:
        self._fmp = fmp

    def get_upcoming_events(
        self, ticker: str, country: Country, within_days: int = 30
    ) -> list[EventRecord]:
        # India: no reliable free source for upcoming events via FMP; skip
        if country == Country.INDIA:
            return []
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
        india_official: IndiaOfficialFundamentalsProvider | None = None,
    ) -> None:
        _yf = yf or YFinanceProvider()
        _fmp = fmp or FMPProvider()
        _fred = fred or FREDProvider()
        _rbi = rbi or RBIProvider()
        _newsapi = newsapi or NewsAPIProvider()
        _india = india_official or IndiaOfficialFundamentalsProvider()

        self.prices = _PriceService(_yf)
        self.fundamentals = _FundamentalService(_india, _fmp, _yf)
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


def _merge_fundamental_snapshots(
    primary: list[FundamentalSnapshot],
    secondary: list[FundamentalSnapshot],
    limit: int,
) -> list[FundamentalSnapshot]:
    if not secondary:
        return primary[:limit]

    primary_by_date = {
        snap.fiscal_date: snap
        for snap in sorted(primary, key=lambda snap: snap.fiscal_date, reverse=True)
    }
    secondary_by_date = {
        snap.fiscal_date: snap
        for snap in sorted(secondary, key=lambda snap: snap.fiscal_date, reverse=True)
    }

    merged: list[FundamentalSnapshot] = []
    all_dates = sorted(
        set(primary_by_date) | set(secondary_by_date),
        reverse=True,
    )
    for fiscal_date in all_dates:
        primary_snap = primary_by_date.get(fiscal_date)
        secondary_snap = secondary_by_date.get(fiscal_date)

        if primary_snap and secondary_snap:
            data = secondary_snap.model_dump()
            for key, value in primary_snap.model_dump().items():
                if value is not None:
                    data[key] = value
            merged.append(FundamentalSnapshot(**data))
        else:
            merged.append(primary_snap or secondary_snap)

    return merged[:limit]


def _needs_vendor_enrichment(snapshots: list[FundamentalSnapshot]) -> bool:
    if not snapshots:
        return False

    # Only chase vendor enrichment when official India data is missing
    # core fields needed for current scoring and the hybrid milestone.
    for snapshot in snapshots:
        if any(
            getattr(snapshot, field) is None
            for field in (
                "revenue",
                "net_income",
                "eps",
                "total_debt",
                "total_equity",
                "debt_equity",
                "roe",
                "roce",
                "promoter_holding",
            )
        ):
            return True
        if snapshot.operating_cash_flow is None and snapshot.free_cash_flow is None:
            return True

    latest = snapshots[0]
    if any(
        getattr(latest, field) is None
        for field in (
            "pe",
            "ev_ebitda",
            "dividend_yield",
            "payout_ratio",
        )
    ):
        return True

    return False

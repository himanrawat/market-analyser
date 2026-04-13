"""Market-aware data provider facade.

The public surface remains:

    dp = get_data_provider()
    dp.prices.get_daily_ohlcv(...)
    dp.fundamentals.get_quarterly_fundamentals(...)
    dp.news.get_stock_news(...)
    dp.events.get_upcoming_events(...)
    dp.macro.get_series(...)

Internally, the implementation is now explicitly split by market:
- India lane: official NSE/BSE fundamentals on disk, NSE runtime metadata/news/
  events, yfinance only as fallback where the official runtime surface is not
  yet complete.
- US lane: FMP primary with yfinance fallback where appropriate.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

from loguru import logger

from pipeline.db.enums import Country
from pipeline.providers.dto import (
    BulkDealRecord,
    DerivativesSentiment,
    EventRecord,
    FundamentalSnapshot,
    InsiderTradeRecord,
    MacroReading,
    MarketBreadthSnapshot,
    MarketDepthSnapshot,
    NewsArticle,
    PriceBar,
    StockProfile,
)
from pipeline.providers.errors import (
    DataProviderError,
    MissingApiKeyError,
    PlanLimitError,
    SymbolNotFoundError,
)
from pipeline.providers.fmp_provider import FMPProvider
from pipeline.providers.fred_provider import FREDProvider
from pipeline.providers.india_market_provider import IndiaMarketProvider
from pipeline.providers.india_official_provider import IndiaOfficialFundamentalsProvider
from pipeline.providers.newsapi_provider import NewsAPIProvider
from pipeline.providers.rbi_provider import RBIProvider
from pipeline.providers.us_market_provider import USMarketProvider
from pipeline.providers.yfinance_provider import YFinanceProvider

_YF_MACRO_INDICATORS = {
    "INDIA_VIX", "USD_INR",
    "NIFTY_50", "SP_500", "NASDAQ", "SENSEX",
    "BRENT_OIL", "GOLD", "US_10Y",
}
_FRED_INDICATORS = {
    "FEDFUNDS", "US_CPI_YOY", "US_GDP_GROWTH", "US_UNEMPLOYMENT", "US_VIX",
}
_RBI_INDICATORS = {
    "INDIA_REPO_RATE", "INDIA_CPI_YOY",
}


class _PriceService:
    """History is still yfinance-backed; India latest quote is official-first."""

    def __init__(self, india_market: IndiaMarketProvider, yf: YFinanceProvider) -> None:
        self._india = india_market
        self._yf = yf

    def get_daily_ohlcv(
        self, ticker: str, country: Country, start: date, end: date
    ) -> list[PriceBar]:
        return self._yf.get_daily_ohlcv(ticker, country, start, end)

    def get_latest_quote(self, ticker: str, country: Country) -> PriceBar:
        if country == Country.INDIA:
            return self._india.get_latest_quote(ticker, country)
        return self._yf.get_latest_quote(ticker, country)


class _FundamentalService:
    """Market-aware routing for profile + quarterly fundamentals."""

    def __init__(
        self,
        india_official: IndiaOfficialFundamentalsProvider,
        india_market: IndiaMarketProvider,
        us_market: USMarketProvider,
        yf: YFinanceProvider,
    ) -> None:
        self._india_official = india_official
        self._india_market = india_market
        self._us_market = us_market
        self._yf = yf

    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]:
        if country == Country.US:
            return self._us_market.get_quarterly_fundamentals(ticker, country, limit)

        official: list[FundamentalSnapshot] = []
        try:
            official = self._india_official.get_quarterly_fundamentals(ticker, country, limit)
        except SymbolNotFoundError:
            logger.debug(f"Official India fundamentals unavailable for {ticker} — trying fallback lane")
        except DataProviderError as exc:
            logger.warning(
                f"Official India fundamentals issue for {ticker}: {exc}. Falling back to vendor lane."
            )

        if official:
            if not _needs_vendor_enrichment(official):
                logger.debug(
                    f"Official India fundamentals already complete for {ticker} — skipping fallback enrichment"
                )
                return official[:limit]
            try:
                vendor = self._yf.get_quarterly_fundamentals(ticker, country, limit)
            except Exception:  # noqa: BLE001
                vendor = []
            return _merge_fundamental_snapshots(official, vendor, limit)

        return self._yf.get_quarterly_fundamentals(ticker, country, limit)

    def get_profile(self, ticker: str, country: Country) -> StockProfile:
        if country == Country.INDIA:
            return self._india_market.get_profile(ticker, country)
        return self._us_market.get_profile(ticker, country)


class _NewsService:
    """Stock news is market-specific; general news prefers NewsAPI first."""

    def __init__(
        self,
        india_market: IndiaMarketProvider,
        us_market: USMarketProvider,
        fmp: FMPProvider,
        newsapi: NewsAPIProvider,
    ) -> None:
        self._india = india_market
        self._us = us_market
        self._fmp = fmp
        self._newsapi = newsapi

    def get_stock_news(
        self, ticker: str, country: Country, since: datetime
    ) -> list[NewsArticle]:
        if country == Country.INDIA:
            return self._india.get_stock_news(ticker, country, since)
        return self._us.get_stock_news(ticker, country, since)

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]:
        try:
            articles = self._newsapi.get_general_news(since, limit)
            if articles:
                return articles[:limit]
        except MissingApiKeyError:
            logger.debug("NewsAPI key missing — falling back to FMP general news")

        try:
            articles = self._fmp.get_general_news(since, limit)
            if articles:
                return articles[:limit]
        except DataProviderError:
            logger.debug("FMP general-latest unavailable — skipping")

        try:
            articles = self._fmp.get_fmp_articles(since, 20)
            if articles:
                return articles[:limit]
        except DataProviderError:
            logger.debug("FMP articles unavailable — skipping")

        try:
            articles = self._fmp.get_stock_news_latest(since, 50)
            if articles:
                return articles[:limit]
        except DataProviderError:
            logger.debug("FMP stock-latest unavailable — skipping")

        return []


class _EventService:
    def __init__(self, india_market: IndiaMarketProvider, us_market: USMarketProvider) -> None:
        self._india = india_market
        self._us = us_market

    def get_upcoming_events(
        self, ticker: str, country: Country, within_days: int = 30
    ) -> list[EventRecord]:
        if country == Country.INDIA:
            return self._india.get_upcoming_events(ticker, country, within_days)
        return self._us.get_upcoming_events(ticker, country, within_days)


class _IndiaDataService:
    """India-only data surfaces: bulk deals, insider trades, depth, derivatives, breadth."""

    def __init__(self, india_market: IndiaMarketProvider) -> None:
        self._india = india_market

    def get_bulk_deals(
        self, ticker: str, country: Country, limit: int = 100
    ) -> list[BulkDealRecord]:
        if country != Country.INDIA:
            return []
        return self._india.get_bulk_deals(ticker, country, limit)

    def get_insider_trades(
        self, ticker: str, country: Country, limit: int = 100
    ) -> list[InsiderTradeRecord]:
        if country != Country.INDIA:
            return []
        return self._india.get_insider_trades(ticker, country, limit)

    def get_market_depth(
        self, ticker: str, country: Country
    ) -> MarketDepthSnapshot | None:
        if country != Country.INDIA:
            return None
        return self._india.get_market_depth(ticker, country)

    def get_derivatives_sentiment(
        self, ticker: str, country: Country
    ) -> DerivativesSentiment | None:
        if country != Country.INDIA:
            return None
        return self._india.get_derivatives_sentiment(ticker, country)

    def get_market_breadth(self) -> MarketBreadthSnapshot | None:
        return self._india.get_market_breadth()

    def get_historical_prices_official(
        self,
        ticker: str,
        country: Country,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[PriceBar]:
        if country != Country.INDIA:
            return []
        return self._india.get_historical_prices_official(
            ticker, country, from_date=from_date, to_date=to_date
        )


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
    """Facade over the separated India and US market lanes."""

    def __init__(
        self,
        yf: YFinanceProvider | None = None,
        fmp: FMPProvider | None = None,
        fred: FREDProvider | None = None,
        rbi: RBIProvider | None = None,
        newsapi: NewsAPIProvider | None = None,
        india_official: IndiaOfficialFundamentalsProvider | None = None,
        india_market: IndiaMarketProvider | None = None,
        us_market: USMarketProvider | None = None,
    ) -> None:
        _yf = yf or YFinanceProvider()
        _fmp = fmp or FMPProvider()
        _fred = fred or FREDProvider()
        _rbi = rbi or RBIProvider()
        _newsapi = newsapi or NewsAPIProvider()
        _india_official = india_official or IndiaOfficialFundamentalsProvider()
        _india_market = india_market or IndiaMarketProvider(yf=_yf)
        _us_market = us_market or USMarketProvider(fmp=_fmp, yf=_yf)

        self.prices = _PriceService(_india_market, _yf)
        self.fundamentals = _FundamentalService(_india_official, _india_market, _us_market, _yf)
        self.news = _NewsService(_india_market, _us_market, _fmp, _newsapi)
        self.events = _EventService(_india_market, _us_market)
        self.macro = _MacroService(_fred, _rbi, _yf)
        self.india = _IndiaDataService(_india_market)

    def health_check(self) -> dict[str, bool]:
        from pipeline.config import settings
        return {
            "yfinance": True,
            "fmp": bool(settings.fmp_api_key),
            "fred": bool(settings.fred_api_key),
            "newsapi": bool(settings.newsapi_key),
            "rbi": True,
        }


@lru_cache(maxsize=1)
def get_data_provider() -> DataProvider:
    dp = DataProvider()
    health = dp.health_check()
    configured = [name for name, enabled in health.items() if enabled]
    missing = [name for name, enabled in health.items() if not enabled]
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
    all_dates = sorted(set(primary_by_date) | set(secondary_by_date), reverse=True)
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
    return any(
        getattr(latest, field) is None
        for field in (
            "pe",
            "ev_ebitda",
            "dividend_yield",
            "payout_ratio",
        )
    )

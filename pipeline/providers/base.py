"""Protocol definitions for each provider responsibility.

The `DataProvider` facade in `registry.py` composes one concrete class per
protocol. Tests and alternate environments can inject fakes by implementing
just the protocol they need."""
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from pipeline.db.enums import Country, IndexName
from pipeline.providers.dto import (
    EventRecord,
    FundamentalSnapshot,
    MacroReading,
    NewsArticle,
    PriceBar,
    StockProfile,
    UniverseConstituent,
)


@runtime_checkable
class PriceProvider(Protocol):
    def get_daily_ohlcv(
        self, ticker: str, country: Country, start: date, end: date
    ) -> list[PriceBar]: ...

    def get_latest_quote(
        self, ticker: str, country: Country
    ) -> PriceBar: ...


@runtime_checkable
class FundamentalProvider(Protocol):
    def get_quarterly_fundamentals(
        self, ticker: str, country: Country, limit: int = 20
    ) -> list[FundamentalSnapshot]: ...

    def get_profile(self, ticker: str, country: Country) -> StockProfile: ...


@runtime_checkable
class NewsProvider(Protocol):
    def get_stock_news(
        self, ticker: str, country: Country, since: datetime
    ) -> list[NewsArticle]: ...

    def get_general_news(self, since: datetime, limit: int = 100) -> list[NewsArticle]: ...


@runtime_checkable
class EventProvider(Protocol):
    def get_upcoming_events(
        self, ticker: str, country: Country, within_days: int = 30
    ) -> list[EventRecord]: ...


@runtime_checkable
class MacroProvider(Protocol):
    def get_series(
        self, indicator: str, start: date, end: date
    ) -> list[MacroReading]: ...


@runtime_checkable
class UniverseProvider(Protocol):
    def get_constituents(self, index_name: IndexName) -> list[UniverseConstituent]: ...

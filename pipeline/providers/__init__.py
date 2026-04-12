"""Data provider abstraction layer.

The rest of the pipeline talks only to the `DataProvider` facade and the
Pydantic DTOs in `dto.py`. Swapping a vendor (e.g. FMP → EODHD) means
writing a new concrete class, not touching scoring or universe code.
"""
from pipeline.providers.dto import (
    EventRecord,
    FundamentalSnapshot,
    MacroReading,
    NewsArticle,
    PriceBar,
    StockProfile,
    UniverseConstituent,
)
from pipeline.providers.errors import (
    DataProviderError,
    MissingApiKeyError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    SymbolNotFoundError,
)
from pipeline.providers.registry import DataProvider, get_data_provider

__all__ = [
    "DataProvider",
    "DataProviderError",
    "EventRecord",
    "FundamentalSnapshot",
    "MacroReading",
    "MissingApiKeyError",
    "NewsArticle",
    "PriceBar",
    "ProviderRateLimitError",
    "ProviderUnavailableError",
    "StockProfile",
    "SymbolNotFoundError",
    "UniverseConstituent",
    "get_data_provider",
]

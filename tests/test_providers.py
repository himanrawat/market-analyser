"""Provider layer tests.

Unit tests use mocks/fakes only — no network calls.
The live smoke test at the bottom is skipped by default; run with:
    pytest -m live tests/test_providers.py
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.db.enums import Country, EventType
from pipeline.providers.cache import JsonCache
from pipeline.providers.dto import NewsArticle, PriceBar, StockProfile
from pipeline.providers.errors import (
    MissingApiKeyError,
    ProviderRateLimitError,
    SymbolNotFoundError,
)
from pipeline.providers.fmp_provider import FMPProvider, _parse_date, _parse_datetime
from pipeline.providers.newsapi_provider import NewsAPIProvider
from pipeline.providers.registry import DataProvider, get_data_provider
from pipeline.providers.yfinance_provider import YFinanceProvider, _yf_symbol


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_cache(tmp_path: Path) -> JsonCache:
    return JsonCache("test", root=tmp_path)


@pytest.fixture()
def yf_provider(tmp_path: Path) -> YFinanceProvider:
    return YFinanceProvider(cache=JsonCache("yf", root=tmp_path))


@pytest.fixture()
def fmp_provider(tmp_path: Path) -> FMPProvider:
    return FMPProvider(cache=JsonCache("fmp", root=tmp_path))


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestJsonCache:
    def test_miss_on_empty(self, tmp_cache: JsonCache) -> None:
        assert tmp_cache.get("ep", {"k": "v"}, timedelta(hours=1)) is None

    def test_roundtrip(self, tmp_cache: JsonCache) -> None:
        data = [{"a": 1}, {"b": 2}]
        tmp_cache.set("ep", {"k": "v"}, data)
        result = tmp_cache.get("ep", {"k": "v"}, timedelta(hours=1))
        assert result == data

    def test_expired_returns_none(self, tmp_cache: JsonCache) -> None:
        tmp_cache.set("ep", {"k": "v"}, {"x": 1})
        result = tmp_cache.get("ep", {"k": "v"}, timedelta(seconds=-1))
        assert result is None

    def test_clear(self, tmp_cache: JsonCache) -> None:
        tmp_cache.set("ep", {"k": "v1"}, "val1")
        tmp_cache.set("ep", {"k": "v2"}, "val2")
        count = tmp_cache.clear()
        assert count == 2
        assert tmp_cache.get("ep", {"k": "v1"}, timedelta(hours=1)) is None

    def test_different_args_different_files(self, tmp_cache: JsonCache) -> None:
        tmp_cache.set("ep", {"k": "a"}, "val_a")
        tmp_cache.set("ep", {"k": "b"}, "val_b")
        assert tmp_cache.get("ep", {"k": "a"}, timedelta(hours=1)) == "val_a"
        assert tmp_cache.get("ep", {"k": "b"}, timedelta(hours=1)) == "val_b"


# ---------------------------------------------------------------------------
# yfinance symbol helper
# ---------------------------------------------------------------------------


class TestYFSymbol:
    def test_india_adds_ns(self) -> None:
        assert _yf_symbol("RELIANCE", Country.INDIA) == "RELIANCE.NS"

    def test_india_already_ns(self) -> None:
        assert _yf_symbol("RELIANCE.NS", Country.INDIA) == "RELIANCE.NS"

    def test_us_passthrough(self) -> None:
        assert _yf_symbol("AAPL", Country.US) == "AAPL"


# ---------------------------------------------------------------------------
# yfinance provider (mocked)
# ---------------------------------------------------------------------------


def _make_ohlcv_df() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"])
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [98.0, 99.0, 100.0],
            "Close": [103.0, 104.0, 105.0],
            "Adj Close": [103.0, 104.0, 105.0],
            "Volume": [1_000_000, 1_100_000, 1_200_000],
        },
        index=idx,
    )
    return df


class TestYFinanceProvider:
    @patch("yfinance.download")
    def test_get_daily_ohlcv_returns_bars(self, mock_dl, yf_provider) -> None:
        mock_dl.return_value = _make_ohlcv_df()
        bars = yf_provider.get_daily_ohlcv(
            "AAPL", Country.US, date(2026, 4, 1), date(2026, 4, 3)
        )
        assert len(bars) == 3
        assert abs(bars[0].close - 103.0) < 1e-9
        assert bars[2].ticker == "AAPL"

    @patch("yfinance.download")
    def test_empty_df_raises_symbol_not_found(self, mock_dl, yf_provider) -> None:
        mock_dl.return_value = pd.DataFrame()
        with pytest.raises(SymbolNotFoundError):
            yf_provider.get_daily_ohlcv(
                "FAKEXYZ", Country.US, date(2026, 1, 1), date(2026, 1, 10)
            )

    @patch("yfinance.download")
    def test_india_ticker_uses_ns_suffix(self, mock_dl, yf_provider) -> None:
        mock_dl.return_value = _make_ohlcv_df()
        yf_provider.get_daily_ohlcv("RELIANCE", Country.INDIA, date(2026, 4, 1), date(2026, 4, 3))
        call_args = mock_dl.call_args
        assert "RELIANCE.NS" in str(call_args)

    @patch("yfinance.Ticker")
    def test_get_profile(self, mock_ticker_cls, yf_provider) -> None:
        mock_t = MagicMock()
        mock_t.info = {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "currency": "USD",
            "marketCap": 3_000_000_000_000,
            "firstTradeDateEpochUtc": 345427200,
        }
        mock_ticker_cls.return_value = mock_t
        profile = yf_provider.get_profile("AAPL", Country.US)
        assert profile.name == "Apple Inc."
        assert profile.market_cap == 3_000_000_000_000
        assert profile.sector == "Technology"


# ---------------------------------------------------------------------------
# FMP provider (mocked)
# ---------------------------------------------------------------------------


class TestFMPProvider:
    def test_missing_key_raises(self, fmp_provider) -> None:
        with patch("pipeline.providers.fmp_provider.settings") as mock_settings:
            mock_settings.fmp_api_key = ""
            with pytest.raises(MissingApiKeyError) as exc:
                fmp_provider._require_key()
            assert "FMP_API_KEY" in str(exc.value)

    @patch("pipeline.providers.fmp_provider.get_json")
    def test_get_profile(self, mock_get, fmp_provider) -> None:
        mock_get.return_value = [
            {
                "companyName": "Reliance Industries",
                "sector": "Energy",
                "industry": "Oil & Gas",
                "currency": "INR",
                "mktCap": 18_000_000_000_000,
                "ipoDate": "1977-11-29",
                "description": "Indian conglomerate.",
            }
        ]
        with patch.object(fmp_provider, "_require_key", return_value="fake_key"):
            profile = fmp_provider.get_profile("RELIANCE", Country.INDIA)
        assert profile.name == "Reliance Industries"
        assert profile.sector == "Energy"
        assert profile.listing_date == date(1977, 11, 29)

    @patch("pipeline.providers.fmp_provider.get_json")
    def test_get_stock_news_filters_by_since(self, mock_get, fmp_provider) -> None:
        mock_get.return_value = [
            {
                "title": "Old news",
                "url": "https://example.com/old",
                "publishedDate": "2026-03-01 10:00:00",
                "site": "fmp",
            },
            {
                "title": "Recent news",
                "url": "https://example.com/recent",
                "publishedDate": "2026-04-10 10:00:00",
                "site": "fmp",
            },
        ]
        since = datetime(2026, 4, 1)
        with patch.object(fmp_provider, "_require_key", return_value="fake_key"):
            articles = fmp_provider.get_stock_news("AAPL", Country.US, since)
        assert len(articles) == 1
        assert articles[0].headline == "Recent news"

    @patch("pipeline.providers.fmp_provider.get_json")
    def test_get_upcoming_events_earnings(self, mock_get, fmp_provider) -> None:
        today = date.today()
        future_date = (today + timedelta(days=5)).isoformat()
        # First call → earnings list; second call → dividends dict; third call → splits list
        mock_get.side_effect = [
            [{"date": future_date, "epsEstimated": 1.5, "revenueEstimated": 100_000}],
            {"historical": []},
            [],
        ]
        with patch.object(fmp_provider, "_require_key", return_value="fake_key"):
            events = fmp_provider.get_upcoming_events("AAPL", Country.US, within_days=30)
        earnings = [e for e in events if e.event_type == EventType.EARNINGS]
        assert len(earnings) == 1
        assert abs(earnings[0].meta["eps_estimate"] - 1.5) < 1e-9

    @patch("pipeline.providers.fmp_provider.get_json")
    def test_get_analyst_forecast_parses_targets_and_estimates(self, mock_get, fmp_provider) -> None:
        mock_get.side_effect = [
            [{"targetHigh": 210, "targetLow": 150, "targetConsensus": 180, "currentPrice": 172}],
            [{"strongBuy": 7, "buy": 9, "hold": 4, "sell": 1, "strongSell": 0, "consensus": "Buy"}],
            [
                {
                    "period": "2026Q2",
                    "date": "2026-06-30",
                    "estimatedEpsAvg": 2.15,
                    "estimatedRevenueAvg": 1000000,
                    "numberAnalystEstimatedEps": 12,
                }
            ],
        ]
        with patch.object(fmp_provider, "_require_key", return_value="fake_key"):
            forecast = fmp_provider.get_analyst_forecast("AAPL", Country.US)

        assert forecast is not None
        assert forecast.target_avg == 180
        assert forecast.buy_count == 16
        assert forecast.sell_count == 1
        assert forecast.consensus_rating == "Buy"
        assert forecast.quarterly_estimates[0].eps_estimate == 2.15

    @patch("pipeline.providers.fmp_provider.get_json")
    def test_get_stock_peers_parses_peer_list(self, mock_get, fmp_provider) -> None:
        mock_get.return_value = [{"peersList": ["MSFT", "NVDA", "GOOG"]}]
        with patch.object(fmp_provider, "_require_key", return_value="fake_key"):
            peers = fmp_provider.get_stock_peers("AAPL", Country.US)
        assert peers == ["MSFT", "NVDA", "GOOG"]


# ---------------------------------------------------------------------------
# FMP parse helpers
# ---------------------------------------------------------------------------


class TestFMPHelpers:
    def test_parse_date_iso(self) -> None:
        assert _parse_date("2026-04-10") == date(2026, 4, 10)

    def test_parse_date_none(self) -> None:
        assert _parse_date(None) is None
        assert _parse_date("") is None

    def test_parse_datetime_various_formats(self) -> None:
        assert _parse_datetime("2026-04-10 14:30:00") == datetime(2026, 4, 10, 14, 30, 0)
        assert _parse_datetime("2026-04-10T14:30:00") == datetime(2026, 4, 10, 14, 30, 0)


# ---------------------------------------------------------------------------
# DataProvider facade
# ---------------------------------------------------------------------------


class TestDataProvider:
    def test_health_check_no_keys(self) -> None:
        # health_check does `from pipeline.config import settings` — patch at source
        with patch("pipeline.config.settings") as ms:
            ms.fmp_api_key = ""
            ms.fred_api_key = ""
            ms.newsapi_key = ""
            dp = DataProvider()
            health = dp.health_check()
        assert health["yfinance"] is True
        assert health["rbi"] is True
        assert health["fmp"] is False
        assert health["fred"] is False
        assert health["newsapi"] is False

    @patch("yfinance.download")
    def test_prices_service_delegates_to_yfinance(self, mock_dl) -> None:
        mock_dl.return_value = _make_ohlcv_df()
        dp = DataProvider()
        bars = dp.prices.get_daily_ohlcv("AAPL", Country.US, date(2026, 4, 1), date(2026, 4, 3))
        assert len(bars) == 3

    def test_fundamentals_fallback_on_missing_fmp_key(self) -> None:
        """If FMP key is absent, fundamentals should fall back to yfinance."""
        dp = DataProvider()

        with patch.object(dp.fundamentals._fmp, "get_quarterly_fundamentals") as mock_fmp, \
             patch.object(dp.fundamentals._yf, "get_quarterly_fundamentals") as mock_yf:
            mock_fmp.side_effect = MissingApiKeyError("fmp", "FMP_API_KEY")
            mock_yf.return_value = []
            result = dp.fundamentals.get_quarterly_fundamentals("AAPL", Country.US)
            mock_yf.assert_called_once()
            assert result == []

    def test_news_falls_back_to_newsapi(self) -> None:
        dp = DataProvider()
        since = datetime(2026, 4, 1)

        with patch.object(dp.news._fmp, "get_general_news") as mock_fmp, \
             patch.object(dp.news._newsapi, "get_general_news") as mock_newsapi:
            mock_fmp.side_effect = MissingApiKeyError("fmp", "FMP_API_KEY")
            mock_newsapi.return_value = [
                NewsArticle(
                    source="newsapi",
                    headline="Market falls",
                    url="https://example.com/1",
                    published_at=datetime(2026, 4, 10, 10, 0),
                )
            ]
            articles = dp.news.get_general_news(since)
            mock_newsapi.assert_called_once()
            assert articles[0].headline == "Market falls"

    def test_macro_routes_yf_indicators(self) -> None:
        dp = DataProvider()
        with patch.object(dp.macro._yf, "get_series") as mock_yf:
            mock_yf.return_value = []
            dp.macro.get_series("US_VIX", date(2026, 1, 1), date(2026, 4, 1))
            mock_yf.assert_called_once_with("US_VIX", date(2026, 1, 1), date(2026, 4, 1))

    def test_macro_routes_fred_indicators(self) -> None:
        dp = DataProvider()
        with patch.object(dp.macro._fred, "get_series") as mock_fred:
            mock_fred.return_value = []
            dp.macro.get_series("FEDFUNDS", date(2026, 1, 1), date(2026, 4, 1))
            mock_fred.assert_called_once()

    def test_macro_routes_rbi_indicators(self) -> None:
        dp = DataProvider()
        with patch.object(dp.macro._rbi, "get_series") as mock_rbi:
            mock_rbi.return_value = []
            dp.macro.get_series("INDIA_REPO_RATE", date(2026, 1, 1), date(2026, 4, 1))
            mock_rbi.assert_called_once()

    def test_macro_unknown_indicator_raises(self) -> None:
        dp = DataProvider()
        with pytest.raises(ValueError, match="Unknown macro indicator"):
            dp.macro.get_series("MADE_UP", date(2026, 1, 1), date(2026, 4, 1))


# ---------------------------------------------------------------------------
# Live smoke test (network required — skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.live
def test_live_yfinance_aapl() -> None:
    """Hits real yfinance. Run with: pytest -m live"""
    dp = DataProvider()
    bars = dp.prices.get_daily_ohlcv(
        "AAPL", Country.US, date(2026, 3, 1), date(2026, 4, 1)
    )
    assert len(bars) > 15  # roughly 23 trading days
    assert all(b.close > 0 for b in bars)


@pytest.mark.live
def test_live_yfinance_reliance() -> None:
    dp = DataProvider()
    bars = dp.prices.get_daily_ohlcv(
        "RELIANCE", Country.INDIA, date(2026, 3, 1), date(2026, 4, 1)
    )
    assert len(bars) > 10
    assert bars[0].country == Country.INDIA


@pytest.mark.live
def test_live_yfinance_vix() -> None:
    dp = DataProvider()
    readings = dp.macro.get_series("US_VIX", date(2026, 3, 1), date(2026, 4, 1))
    assert len(readings) > 10
    assert all(r.value > 0 for r in readings)

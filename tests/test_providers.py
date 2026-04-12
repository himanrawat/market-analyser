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
from pipeline.providers.dto import FundamentalSnapshot, NewsArticle, PriceBar, StockProfile
from pipeline.providers.errors import (
    MissingApiKeyError,
    PlanLimitError,
    ProviderRateLimitError,
    SymbolNotFoundError,
)
from pipeline.providers.fmp_provider import FMPProvider, _parse_date, _parse_datetime
from pipeline.providers.india_official_provider import IndiaOfficialFundamentalsProvider
from pipeline.providers.newsapi_provider import NewsAPIProvider
from pipeline.providers.registry import DataProvider, get_data_provider
from pipeline.providers.yfinance_provider import YFinanceProvider, _yf_symbol, _yf_symbols


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


@pytest.fixture()
def india_official_provider(tmp_path: Path) -> IndiaOfficialFundamentalsProvider:
    return IndiaOfficialFundamentalsProvider(data_dir=tmp_path)


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


class TestYFSymbols:
    def test_india_returns_ns_then_bo(self) -> None:
        assert _yf_symbols("RELIANCE", Country.INDIA) == ["RELIANCE.NS", "RELIANCE.BO"]

    def test_india_already_suffixed_no_duplicate(self) -> None:
        assert _yf_symbols("RELIANCE.NS", Country.INDIA) == ["RELIANCE.NS"]

    def test_us_single_symbol(self) -> None:
        assert _yf_symbols("AAPL", Country.US) == ["AAPL"]


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
    def test_india_ticker_tries_ns_first(self, mock_dl, yf_provider) -> None:
        mock_dl.return_value = _make_ohlcv_df()
        yf_provider.get_daily_ohlcv("RELIANCE", Country.INDIA, date(2026, 4, 1), date(2026, 4, 3))
        first_call_symbol = mock_dl.call_args_list[0][0][0]
        assert first_call_symbol == "RELIANCE.NS"

    @patch("yfinance.download")
    def test_india_ticker_falls_back_to_bo_when_ns_empty(self, mock_dl, yf_provider) -> None:
        # First call (.NS) returns empty; second call (.BO) returns data
        mock_dl.side_effect = [pd.DataFrame(), _make_ohlcv_df()]
        bars = yf_provider.get_daily_ohlcv("RELIANCE", Country.INDIA, date(2026, 4, 1), date(2026, 4, 3))
        assert len(bars) == 3
        symbols_tried = [c[0][0] for c in mock_dl.call_args_list]
        assert symbols_tried == ["RELIANCE.NS", "RELIANCE.BO"]

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
# Official India provider
# ---------------------------------------------------------------------------


class TestIndiaOfficialProvider:
    def test_get_quarterly_fundamentals_from_nse_json_computes_ratios(
        self,
        india_official_provider: IndiaOfficialFundamentalsProvider,
    ) -> None:
        root = india_official_provider.data_dir
        (root / "nse" / "financials").mkdir(parents=True, exist_ok=True)
        (root / "nse" / "shareholding").mkdir(parents=True, exist_ok=True)

        (root / "nse" / "financials" / "RELIANCE.json").write_text(
            json.dumps(
                [
                    {
                        "fiscal_date": "2025-12-31",
                        "revenue": 1000,
                        "net_income": 100,
                        "eps": 10,
                        "total_debt": 200,
                        "total_equity": 500,
                        "operating_cash_flow": 140,
                        "capital_expenditure": -20,
                        "ebit": 150,
                        "ebitda": 180,
                        "enterprise_value": 900,
                        "close_price": 120,
                        "dividend_per_share": 2.4,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (root / "nse" / "shareholding" / "RELIANCE.json").write_text(
            json.dumps(
                [
                    {
                        "as_of_date": "2025-12-31",
                        "promoter_pct": 52.5,
                    }
                ]
            ),
            encoding="utf-8",
        )

        snapshots = india_official_provider.get_quarterly_fundamentals(
            "RELIANCE",
            Country.INDIA,
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.debt_equity == pytest.approx(0.4)
        assert snap.roe == pytest.approx(20.0)
        assert snap.roce == pytest.approx(21.4285714286)
        assert snap.free_cash_flow == pytest.approx(120.0)
        assert snap.pe == pytest.approx(12.0)
        assert snap.ev_ebitda == pytest.approx(5.0)
        assert snap.dividend_yield == pytest.approx(2.0)
        assert snap.payout_ratio == pytest.approx(0.24)
        assert snap.promoter_holding == pytest.approx(52.5)

    def test_get_quarterly_fundamentals_falls_back_to_bse_file(
        self,
        india_official_provider: IndiaOfficialFundamentalsProvider,
    ) -> None:
        root = india_official_provider.data_dir
        (root / "bse" / "financials").mkdir(parents=True, exist_ok=True)
        (root / "bse" / "financials" / "INFY.csv").write_text(
            "fiscal_date,revenue,net_income,eps\n2025-09-30,2000,400,20\n",
            encoding="utf-8",
        )

        snapshots = india_official_provider.get_quarterly_fundamentals(
            "INFY",
            Country.INDIA,
        )

        assert len(snapshots) == 1
        assert snapshots[0].ticker == "INFY"
        assert snapshots[0].fiscal_date == date(2025, 9, 30)
        assert snapshots[0].revenue == 2000

    def test_get_quarterly_fundamentals_parses_importer_style_keys(
        self,
        india_official_provider: IndiaOfficialFundamentalsProvider,
    ) -> None:
        root = india_official_provider.data_dir
        (root / "nse" / "financials").mkdir(parents=True, exist_ok=True)
        (root / "nse" / "shareholding").mkdir(parents=True, exist_ok=True)

        (root / "nse" / "financials" / "RELIANCE.json").write_text(
            json.dumps(
                {
                    "financials": [
                        {
                            "period_ended": "2025-12-31",
                            "revenue": 1000,
                            "net_income": 100,
                            "eps": 10,
                            "total_debt": 200,
                            "total_equity": 500,
                            "operating_cash_flow": 140,
                            "capital_expenditure": -20,
                            "ebit": 150,
                            "ebitda": 180,
                            "enterprise_value": 900,
                            "close_price": 120,
                            "dividend_per_share": 2.4,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "nse" / "shareholding" / "RELIANCE.json").write_text(
            json.dumps(
                {
                    "shareholding": [
                        {
                            "as_of_date": "2025-12-31",
                            "promoter": 52.5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        snapshots = india_official_provider.get_quarterly_fundamentals(
            "RELIANCE",
            Country.INDIA,
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.fiscal_date == date(2025, 12, 31)
        assert snap.promoter_holding == pytest.approx(52.5)

    def test_get_quarterly_fundamentals_parses_live_nse_fetch_shape(
        self,
        india_official_provider: IndiaOfficialFundamentalsProvider,
    ) -> None:
        root = india_official_provider.data_dir
        (root / "nse" / "financials").mkdir(parents=True, exist_ok=True)
        (root / "nse" / "shareholding").mkdir(parents=True, exist_ok=True)

        (root / "nse" / "financials" / "RELIANCE.json").write_text(
            json.dumps(
                {
                    "financials": [
                        {
                            "fiscal_date": "31-Dec-2024",
                            "period": "Third Quarter",
                            "revenue": 13000000.0,
                            "net_income": 900000.0,
                            "eps": 7.1,
                            "ebit": 1200000.0,
                            "interest_expense": 200000.0,
                            "tax_expense": 300000.0,
                            "consolidated": "Consolidated",
                            "xbrl": "https://example.com/consolidated.xml",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (root / "nse" / "shareholding" / "RELIANCE.json").write_text(
            json.dumps(
                {
                    "shareholding": [
                        {
                            "as_of_date": "31-DEC-2024",
                            "promoter_pct": 50.13,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        snapshots = india_official_provider.get_quarterly_fundamentals(
            "RELIANCE",
            Country.INDIA,
        )

        assert len(snapshots) == 1
        snap = snapshots[0]
        assert snap.fiscal_date == date(2024, 12, 31)
        assert snap.period == "Third Quarter"
        assert snap.revenue == 13000000.0
        assert snap.net_income == 900000.0
        assert snap.eps == pytest.approx(7.1)
        assert snap.promoter_holding == pytest.approx(50.13)


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

    def test_india_fundamentals_merge_official_and_vendor(self) -> None:
        official_provider = MagicMock()
        official_provider.get_quarterly_fundamentals.return_value = [
            FundamentalSnapshot(
                ticker="RELIANCE",
                country=Country.INDIA,
                fiscal_date=date(2025, 12, 31),
                period="2025Q4",
                revenue=1000.0,
                net_income=100.0,
                eps=10.0,
                total_debt=200.0,
                total_equity=500.0,
                debt_equity=0.4,
                operating_cash_flow=140.0,
                free_cash_flow=120.0,
                roe=20.0,
                promoter_holding=52.0,
            )
        ]
        dp = DataProvider(india_official=official_provider)

        # India vendor lane is now yfinance (FMP removed for India)
        with patch.object(dp.fundamentals._yf, "get_quarterly_fundamentals") as mock_yf:
            mock_yf.return_value = [
                FundamentalSnapshot(
                    ticker="RELIANCE",
                    country=Country.INDIA,
                    fiscal_date=date(2025, 12, 31),
                    period="2025Q4",
                    revenue=None,
                    net_income=None,
                    eps=None,
                    pe=18.0,
                    pb=3.0,
                    ev_ebitda=11.0,
                    dividend_yield=1.2,
                    payout_ratio=0.35,
                )
            ]
            merged = dp.fundamentals.get_quarterly_fundamentals("RELIANCE", Country.INDIA)

        assert len(merged) == 1
        assert merged[0].revenue == 1000.0
        assert merged[0].promoter_holding == 52.0
        assert merged[0].pe == 18.0
        assert merged[0].pb == 3.0
        assert merged[0].payout_ratio == 0.35

    def test_india_fundamentals_fall_back_to_vendor_when_official_missing(self) -> None:
        official_provider = MagicMock()
        official_provider.get_quarterly_fundamentals.side_effect = SymbolNotFoundError(
            "RELIANCE",
            "india_official",
        )
        dp = DataProvider(india_official=official_provider)

        # India vendor lane is now yfinance (FMP removed for India)
        with patch.object(dp.fundamentals._yf, "get_quarterly_fundamentals") as mock_yf:
            mock_yf.return_value = [
                FundamentalSnapshot(
                    ticker="RELIANCE",
                    country=Country.INDIA,
                    fiscal_date=date(2025, 12, 31),
                    period="2025Q4",
                    revenue=1000.0,
                )
            ]
            rows = dp.fundamentals.get_quarterly_fundamentals("RELIANCE", Country.INDIA)

        assert len(rows) == 1
        assert rows[0].revenue == 1000.0

    def test_india_complete_official_fundamentals_skip_vendor_enrichment(self) -> None:
        official_provider = MagicMock()
        official_provider.get_quarterly_fundamentals.return_value = [
            FundamentalSnapshot(
                ticker="RELIANCE",
                country=Country.INDIA,
                fiscal_date=date(2025, 12, 31),
                period="2025Q4",
                revenue=1000.0,
                net_income=100.0,
                eps=10.0,
                total_debt=200.0,
                total_equity=500.0,
                debt_equity=0.4,
                operating_cash_flow=140.0,
                free_cash_flow=120.0,
                roe=20.0,
                roce=21.4,
                gross_margin=40.0,
                operating_margin=15.0,
                net_margin=10.0,
                pe=12.0,
                peg=1.1,
                pb=2.0,
                ev_ebitda=5.0,
                dividend_per_share=2.4,
                dividend_yield=2.0,
                payout_ratio=0.24,
                promoter_holding=52.5,
            )
        ]
        dp = DataProvider(india_official=official_provider)

        with patch.object(dp.fundamentals, "_get_vendor_fundamentals") as mock_vendor:
            rows = dp.fundamentals.get_quarterly_fundamentals("RELIANCE", Country.INDIA)

        mock_vendor.assert_not_called()
        assert len(rows) == 1
        assert rows[0].pe == 12.0

    def test_india_sample_style_official_fundamentals_skip_vendor_enrichment(self) -> None:
        official_provider = MagicMock()
        official_provider.get_quarterly_fundamentals.return_value = [
            FundamentalSnapshot(
                ticker="RELIANCE",
                country=Country.INDIA,
                fiscal_date=date(2025, 12, 31),
                period="2025Q4",
                revenue=1000.0,
                net_income=100.0,
                eps=10.0,
                total_debt=200.0,
                total_equity=500.0,
                debt_equity=0.4,
                operating_cash_flow=140.0,
                free_cash_flow=120.0,
                roe=20.0,
                roce=21.4285714286,
                pe=12.0,
                ev_ebitda=5.0,
                dividend_per_share=2.4,
                dividend_yield=2.0,
                payout_ratio=0.24,
                promoter_holding=52.5,
            )
        ]
        dp = DataProvider(india_official=official_provider)

        with patch.object(dp.fundamentals, "_get_vendor_fundamentals") as mock_vendor:
            rows = dp.fundamentals.get_quarterly_fundamentals("RELIANCE", Country.INDIA)

        mock_vendor.assert_not_called()
        assert len(rows) == 1
        assert rows[0].promoter_holding == 52.5

    def test_india_vendor_enrichment_failure_after_official_is_silent(self) -> None:
        official_provider = MagicMock()
        official_provider.get_quarterly_fundamentals.return_value = [
            FundamentalSnapshot(
                ticker="RELIANCE",
                country=Country.INDIA,
                fiscal_date=date(2024, 12, 31),
                period="Third Quarter",
                revenue=24386500.0,
                net_income=2180400.0,
                eps=13.7,
                promoter_holding=50.13,
            )
        ]
        dp = DataProvider(india_official=official_provider)

        with (
            patch.object(dp.fundamentals._fmp, "get_quarterly_fundamentals", side_effect=PlanLimitError("fmp", "url")),
            patch.object(dp.fundamentals._yf, "get_quarterly_fundamentals", side_effect=KeyError("Timestamp('2025-12-31 00:00:00')")),
            patch("pipeline.providers.registry.logger.debug") as mock_debug,
            patch("pipeline.providers.registry.logger.warning") as mock_warning,
        ):
            rows = dp.fundamentals.get_quarterly_fundamentals("RELIANCE", Country.INDIA)

        assert len(rows) == 1
        assert rows[0].revenue == 24386500.0
        mock_debug.assert_not_called()
        mock_warning.assert_not_called()

    def test_news_uses_newsapi_as_primary(self) -> None:
        dp = DataProvider()
        since = datetime(2026, 4, 1)

        with patch.object(dp.news._newsapi, "get_general_news") as mock_newsapi, \
             patch.object(dp.news._fmp, "get_general_news") as mock_fmp:
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
            mock_fmp.assert_not_called()
            assert articles[0].headline == "Market falls"

    def test_news_falls_back_to_fmp_when_newsapi_key_missing(self) -> None:
        dp = DataProvider()
        since = datetime(2026, 4, 1)

        with patch.object(dp.news._newsapi, "get_general_news") as mock_newsapi, \
             patch.object(dp.news._fmp, "get_general_news") as mock_fmp:
            mock_newsapi.side_effect = MissingApiKeyError("newsapi", "NEWSAPI_KEY")
            mock_fmp.return_value = [
                NewsArticle(
                    source="fmp",
                    headline="Rate hike",
                    url="https://example.com/2",
                    published_at=datetime(2026, 4, 10, 10, 0),
                )
            ]
            articles = dp.news.get_general_news(since)
            mock_fmp.assert_called_once()
            assert articles[0].headline == "Rate hike"

    def test_macro_routes_yf_indicators(self) -> None:
        dp = DataProvider()
        with patch.object(dp.macro._yf, "get_series") as mock_yf:
            mock_yf.return_value = []
            dp.macro.get_series("INDIA_VIX", date(2026, 1, 1), date(2026, 4, 1))
            mock_yf.assert_called_once_with("INDIA_VIX", date(2026, 1, 1), date(2026, 4, 1))

    def test_macro_us_vix_routes_to_fred(self) -> None:
        dp = DataProvider()
        with patch.object(dp.macro._fred, "get_series") as mock_fred, \
             patch.object(dp.macro._yf, "get_series") as mock_yf:
            mock_fred.return_value = []
            dp.macro.get_series("US_VIX", date(2026, 1, 1), date(2026, 4, 1))
            mock_fred.assert_called_once()
            mock_yf.assert_not_called()

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
def test_live_fred_us_vix() -> None:
    """US VIX now comes from FRED (VIXCLS). Run with: pytest -m live"""
    dp = DataProvider()
    readings = dp.macro.get_series("US_VIX", date(2026, 3, 1), date(2026, 4, 1))
    assert len(readings) > 10
    assert all(r.value > 0 for r in readings)

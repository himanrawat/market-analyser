from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from pipeline.db import init_db
from pipeline.db.base import _session_factory, get_engine, get_session
from pipeline.db.enums import Country, IndexName
from pipeline.db.models import RebalanceSnapshot, Score, Stock
from pipeline.providers.dto import FundamentalSnapshot, MacroReading, PriceBar
from pipeline.scheduler import (
    _needs_official_india_fetch,
    _select_official_india_batch_candidates,
    run_pipeline,
)


def _make_price_bars(ticker: str, country: Country) -> list[PriceBar]:
    start = date(2025, 1, 1)
    bars: list[PriceBar] = []
    price = 100.0
    for offset in range(320):
        day = start + timedelta(days=offset)
        price *= 1.001
        bars.append(
            PriceBar(
                ticker=ticker,
                country=country,
                date=day,
                open=price * 0.99,
                high=price * 1.01,
                low=price * 0.98,
                close=price,
                adj_close=price,
                volume=2_000_000,
            )
        )
    return bars


def _make_fundamentals(ticker: str, country: Country) -> list[FundamentalSnapshot]:
    rows: list[FundamentalSnapshot] = []
    for i in range(20):
        fiscal = date(2026, 3, 31) - timedelta(days=90 * i)
        rows.append(
            FundamentalSnapshot(
                ticker=ticker,
                country=country,
                fiscal_date=fiscal,
                period=f"{fiscal.year}Q{((fiscal.month - 1) // 3) + 1}",
                revenue=1_000_000 + (20 - i) * 25_000,
                net_income=150_000 + (20 - i) * 5_000,
                eps=5.0 + (20 - i) * 0.1,
                total_debt=100_000,
                total_equity=800_000,
                debt_equity=0.12,
                operating_cash_flow=180_000,
                free_cash_flow=140_000,
                roe=22.0,
                roce=18.0,
                gross_margin=55.0,
                operating_margin=24.0,
                net_margin=15.0,
                pe=18.0,
                peg=1.2,
                pb=3.4,
                ev_ebitda=12.0,
                dividend_per_share=1.5,
                dividend_yield=1.2,
                payout_ratio=0.35,
                promoter_holding=52.0,
            )
        )
    return rows


def _series(indicator: str, start: date, count: int, base: float, step: float = 0.1) -> list[MacroReading]:
    return [
        MacroReading(indicator=indicator, date=start + timedelta(days=i), value=base + i * step)
        for i in range(count)
    ]


def test_run_pipeline_persists_snapshot(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setattr("pipeline.config.settings.database_url", f"sqlite:///{db_path}")
    get_engine.cache_clear()
    _session_factory.cache_clear()
    init_db()

    with get_session() as session:
        session.add(
            Stock(
                ticker="INFY",
                country=Country.INDIA,
                name="Infosys Ltd.",
                sector="Technology",
                industry="IT Services",
                currency="INR",
                market_cap=3_000_000_000_000,
                listing_date=date(2000, 1, 1),
            )
        )

    fake_provider = SimpleNamespace(
        prices=SimpleNamespace(
            get_daily_ohlcv=lambda ticker, country, start, end: _make_price_bars(ticker, country)
        ),
        fundamentals=SimpleNamespace(
            get_quarterly_fundamentals=lambda ticker, country, limit=20: _make_fundamentals(ticker, country)
        ),
        events=SimpleNamespace(get_upcoming_events=lambda ticker, country, within_days=120: []),
        news=SimpleNamespace(get_general_news=lambda since, limit=100: []),
        india=SimpleNamespace(
            _india=None,
            get_bulk_deals=lambda ticker, country, limit=50: [],
            get_insider_trades=lambda ticker, country, limit=50: [],
            get_market_depth=lambda ticker, country: None,
            get_derivatives_sentiment=lambda ticker, country: None,
            get_market_breadth=lambda: None,
        ),
        macro=SimpleNamespace(
            get_series=lambda indicator, start, end: {
                "US_VIX": _series("US_VIX", start, 30, 18.0),
                "INDIA_VIX": _series("INDIA_VIX", start, 30, 14.0),
                "NIFTY_50": _series("NIFTY_50", start, 260, 20000.0, 5.0),
                "SP_500": _series("SP_500", start, 260, 5000.0, 1.0),
                "USD_INR": _series("USD_INR", start, 30, 83.0, 0.01),
                "BRENT_OIL": _series("BRENT_OIL", start, 30, 80.0, 0.2),
                "US_10Y": _series("US_10Y", start, 30, 4.2, 0.01),
                "FEDFUNDS": _series("FEDFUNDS", start, 13, 5.0, 0.0),
                "US_CPI_YOY": _series("US_CPI_YOY", start, 13, 300.0, 1.0),
                "INDIA_REPO_RATE": _series("INDIA_REPO_RATE", start, 13, 6.5, 0.0),
                "INDIA_CPI_YOY": _series("INDIA_CPI_YOY", start, 13, 180.0, 0.8),
            }[indicator]
        ),
    )

    with (
        patch("pipeline.scheduler.get_data_provider", return_value=fake_provider),
        patch("pipeline.scheduler.UniverseLoader.refresh") as refresh_mock,
        patch(
            "pipeline.scheduler.UniverseLoader.get_active_tickers",
            return_value=[("INFY", Country.INDIA)],
        ) as active_tickers_mock,
        patch("pipeline.scheduler.fetch_nse_official_batch"),
        patch("pipeline.scheduler.TelegramNotifier.send_monthly_digest", return_value=False),
        patch("pipeline.scheduler.TelegramNotifier.send_text", return_value=False),
    ):
        run_pipeline(as_of=date(2026, 4, 7), fresh_capital=1000, picks_per_bucket=10)

    refresh_mock.assert_called_once_with(indexes=[IndexName.NIFTY_500])
    active_tickers_mock.assert_called_once_with(
        country=Country.INDIA,
        index=IndexName.NIFTY_500,
    )

    with get_session() as session:
        snapshot = session.execute(select(RebalanceSnapshot)).scalar_one()
        scores = session.execute(select(Score)).scalars().all()

    assert snapshot.run_date == date(2026, 4, 7)
    assert snapshot.universe_size_raw == 1
    assert snapshot.universe_size_filtered == 1
    assert len(scores) > 0


@pytest.mark.india
def test_select_official_india_batch_candidates_prioritizes_seed_names(tmp_path) -> None:
    data_dir = tmp_path / "official_india"
    (data_dir / "nse" / "financials").mkdir(parents=True, exist_ok=True)
    (data_dir / "nse" / "shareholding").mkdir(parents=True, exist_ok=True)

    # RELIANCE is already warm and should be skipped.
    (data_dir / "nse" / "financials" / "RELIANCE.json").write_text("{}", encoding="utf-8")
    (data_dir / "nse" / "shareholding" / "RELIANCE.json").write_text("{}", encoding="utf-8")

    candidates = _select_official_india_batch_candidates(
        [
            ("RELIANCE", Country.INDIA),
            ("TCS", Country.INDIA),
            ("INFY", Country.INDIA),
            ("ITC", Country.INDIA),
            ("HINDUNILVR", Country.INDIA),
            ("SBIN", Country.INDIA),
            ("AAPL", Country.US),
        ],
        batch_size=3,
        data_dir=data_dir,
    )

    assert candidates == ["TCS", "INFY", "ITC"]


@pytest.mark.india
def test_needs_official_india_fetch_requires_both_kinds(tmp_path) -> None:
    data_dir = tmp_path / "official_india"
    (data_dir / "nse" / "financials").mkdir(parents=True, exist_ok=True)
    (data_dir / "nse" / "shareholding").mkdir(parents=True, exist_ok=True)

    assert _needs_official_india_fetch("RELIANCE", data_dir) is True

    (data_dir / "nse" / "financials" / "RELIANCE.json").write_text("{}", encoding="utf-8")
    assert _needs_official_india_fetch("RELIANCE", data_dir) is True

    (data_dir / "nse" / "shareholding" / "RELIANCE.json").write_text("{}", encoding="utf-8")
    assert _needs_official_india_fetch("RELIANCE", data_dir) is False

"""Tests for all FastAPI routers.

Uses an in-memory SQLite database so tests are fully isolated.
All pipeline DB calls are pointed at the test DB via the get_db dependency override.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_db
from api.main import app
from api.routers import kite as kite_router
from pipeline.db.base import Base
from pipeline.db.enums import (
    ActionType,
    Broker,
    Bucket,
    Country,
    MacroRegime,
    NewsCategory,
    NewsStream,
    SentimentLabel,
    ShockBanner,
)
from pipeline.db.models import (
    Holding,
    MacroSnapshot,
    NewsItem,
    RebalanceSnapshot,
    Score,
    SettingKV,
    ShockEvent,
    Stock,
    TradeJournalEntry,
)

# ---------------------------------------------------------------------------
# Test database setup
# ---------------------------------------------------------------------------

_TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,   # all connections share the same in-memory DB
)
Base.metadata.create_all(_TEST_ENGINE)
_TestSession = sessionmaker(bind=_TEST_ENGINE, autocommit=False, autoflush=False)


def _get_test_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _get_test_db


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows between tests."""
    yield
    with _TestSession() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    with _TestSession() as session:
        yield session


@pytest.fixture(autouse=True)
def stub_stock_detail_provider():
    with patch("api.routers.stocks.FMPProvider") as mock_cls:
        provider = mock_cls.return_value
        provider.get_analyst_forecast.return_value = None
        provider.get_stock_peers.return_value = []
        provider.get_upcoming_events.return_value = []
        provider.get_stock_news.return_value = []
        provider.get_profile.return_value = None
        provider.get_quarterly_fundamentals.return_value = []
        yield provider


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_stock(db, ticker="AAPL", country=Country.US, sector="Technology") -> Stock:
    stock = Stock(
        ticker=ticker, country=country, name=f"{ticker} Inc",
        currency="USD", sector=sector,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


def _seed_snapshot(db) -> RebalanceSnapshot:
    snap = RebalanceSnapshot(
        run_date=date(2026, 4, 7),
        run_started_at=datetime(2026, 4, 6, 20, 0, 0),
        macro_regime=MacroRegime.RISK_ON,
        shock_regime=False,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def _seed_score(db, snapshot, stock, bucket=Bucket.QUALITY_MOMENTUM, rank=1) -> Score:
    score = Score(
        snapshot_id=snapshot.id,
        stock_id=stock.id,
        bucket=bucket,
        score=85.0,
        qualified=True,
        rank=rank,
        factor_scores={"roe_5yr_avg": 15.0, "momentum_12m_1m": 18.0},
    )
    db.add(score)
    db.commit()
    db.refresh(score)
    return score


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_returns_200_empty_db(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "macro" in data
        assert "shock" in data
        assert data["shock"]["active"] is False

    def test_with_macro_snapshot(self, client, db):
        db.add(MacroSnapshot(
            date=date(2026, 4, 6),
            india_vix=15.0, us_vix=18.0,
            nifty_50_close=22000, nifty_50_200dma=20000,
            sp_500_close=5200, sp_500_200dma=5000,
            fed_funds_rate=5.25, usd_inr=83.5,
        ))
        db.commit()
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["macro"]["regime"] == "risk_on"
        assert data["vix"]["india_vix"] == 15.0
        assert data["vix"]["us_vix"] == 18.0

    def test_shock_active_when_red_event_undismissed(self, client, db):
        db.add(ShockEvent(
            triggered_at=datetime.now(tz=timezone.utc),
            banner=ShockBanner.RED,
            headline="Market panic",
            source="Reuters",
            matched_keywords=["war"],
        ))
        db.commit()
        r = client.get("/api/dashboard")
        assert r.json()["shock"]["active"] is True


# ---------------------------------------------------------------------------
# Kite
# ---------------------------------------------------------------------------

class TestKite:
    def test_status_reads_api_key_from_settings(self, client, monkeypatch):
        monkeypatch.setattr(kite_router.settings, "kite_api_key", "kite-test-key")

        r = client.get("/api/kite/status")

        assert r.status_code == 200
        assert r.json()["api_key_set"] is True
        assert r.json()["connected"] is False

    def test_callback_saves_token_and_syncs_holdings(self, client, db, monkeypatch):
        stock = Stock(
            ticker="INFY",
            country=Country.INDIA,
            name="Infosys Ltd",
            sector="Technology",
            currency="INR",
        )
        db.add(stock)
        db.commit()

        monkeypatch.setattr(kite_router.settings, "kite_api_key", "kite-test-key")
        monkeypatch.setattr(kite_router.settings, "kite_api_secret", "kite-test-secret")
        monkeypatch.setattr(kite_router.settings, "frontend_url", "http://localhost:3000")

        class FakeKite:
            def __init__(self):
                self.access_token: str | None = None

            def generate_session(self, request_token: str, api_secret: str):
                assert request_token == "req-token"
                assert api_secret == "kite-test-secret"
                return {"access_token": "access-123"}

            def set_access_token(self, access_token: str) -> None:
                self.access_token = access_token

            def holdings(self):
                assert self.access_token == "access-123"
                return [
                    {"tradingsymbol": "INFY", "quantity": 5, "average_price": 1500.0},
                    {"tradingsymbol": "SBIN", "quantity": 0, "average_price": 700.0},
                ]

        monkeypatch.setattr(kite_router, "_get_kite", lambda: FakeKite())

        r = client.get(
            "/api/kite/callback",
            params={"request_token": "req-token", "status": "success"},
            follow_redirects=False,
        )

        assert r.status_code == 307
        assert (
            r.headers["location"]
            == "http://localhost:3000/settings?kite=connected&synced=1&skipped=1"
        )

        kv_rows = db.execute(select(SettingKV)).scalars().all()
        kv = {row.key: row.value for row in kv_rows}
        assert kv["kite_access_token"] == "access-123"
        assert kv["kite_token_date"] == str(date.today())

        holding = db.execute(
            select(Holding).join(Stock).where(Stock.ticker == "INFY", Stock.country == Country.INDIA)
        ).scalar_one()
        assert holding.quantity == 5.0
        assert holding.avg_buy_price == 1500.0
        assert holding.broker == Broker.KITE


# ---------------------------------------------------------------------------
# Ranked lists
# ---------------------------------------------------------------------------

class TestRanked:
    def test_no_snapshot_returns_empty(self, client):
        r = client.get("/api/ranked")
        assert r.status_code == 200
        assert r.json()["lists"] == []

    def test_returns_list_with_snapshot(self, client, db):
        stock = _seed_stock(db)
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.get("/api/ranked")
        assert r.status_code == 200
        lists = r.json()["lists"]
        assert len(lists) > 0

    def test_bucket_filter_works(self, client, db):
        stock = _seed_stock(db)
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock, bucket=Bucket.QUALITY_MOMENTUM)
        r = client.get("/api/ranked?bucket=quality_momentum&country=US")
        assert r.status_code == 200
        lists = r.json()["lists"]
        assert all(lst["bucket"] == "quality_momentum" for lst in lists)

    def test_run_date_populated(self, client, db):
        stock = _seed_stock(db)
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.get("/api/ranked")
        assert r.json()["run_date"] == "2026-04-07"


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class TestActions:
    def test_no_snapshot_404(self, client):
        r = client.get("/api/actions")
        assert r.status_code == 404

    def test_returns_diff_with_snapshot(self, client, db):
        stock = _seed_stock(db)
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.get("/api/actions")
        assert r.status_code == 200
        data = r.json()
        assert "buys" in data
        assert "sells" in data
        assert data["run_date"] == "2026-04-07"

    def test_unowned_stock_is_buy(self, client, db):
        stock = _seed_stock(db, ticker="TSLA")
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.get("/api/actions")
        tickers = [a["ticker"] for a in r.json()["buys"]]
        assert "TSLA" in tickers

    def test_skip_month(self, client):
        r = client.post("/api/actions/skip-month", json={"reason": "Market uncertain"})
        assert r.status_code == 201
        assert r.json()["status"] == "skipped"

    def test_refresh_prices_returns_dict(self, client, db):
        stock = _seed_stock(db)
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        with patch("pipeline.providers.registry.get_data_provider") as mock_prov:
            mock_prov.return_value.prices.return_value = None
            r = client.get("/api/actions/refresh-prices")
        assert r.status_code == 200
        assert "updated" in r.json()

    def test_capital_plan_populates_suggested_amounts(self, client, db):
        stock = _seed_stock(db, ticker="NVDA")
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.get("/api/actions?fresh_capital=10000")
        assert r.status_code == 200
        data = r.json()
        assert data["buys"][0]["suggested_amount"] is not None
        assert "NVDA|quality_momentum" in data["plan"]["action_amounts"]

    def test_execute_buy_creates_holding_and_journal(self, client, db):
        stock = _seed_stock(db, ticker="AMD")
        snap = _seed_snapshot(db)
        _seed_score(db, snap, stock)
        r = client.post(
            "/api/actions/AMD/execute",
            json={
                "action": "buy",
                "bucket": "quality_momentum",
                "country": "US",
                "actual_fill_price": 175.0,
                "qty": 2.0,
            },
        )
        assert r.status_code == 201

        holdings = db.execute(select(Holding).where(Holding.stock_id == stock.id)).scalars().all()
        assert len(holdings) == 1
        assert holdings[0].quantity == 2.0

        journal = db.execute(select(TradeJournalEntry).where(TradeJournalEntry.stock_id == stock.id)).scalar_one()
        assert journal.action_type == ActionType.BUY
        assert journal.quantity == 2.0

    def test_execute_sell_requires_lesson(self, client, db):
        stock = _seed_stock(db, ticker="SHOP")
        db.add(
            Holding(
                stock_id=stock.id,
                quantity=3.0,
                avg_buy_price=100.0,
                buy_date=date(2025, 1, 1),
                broker=Broker.VESTED,
            )
        )
        db.commit()
        _seed_snapshot(db)

        r = client.post(
            "/api/actions/SHOP/execute",
            json={
                "action": "sell",
                "bucket": "quality_momentum",
                "country": "US",
                "actual_fill_price": 120.0,
                "qty": 3.0,
            },
        )
        assert r.status_code == 400

    def test_execute_sell_removes_holding_and_logs_lesson(self, client, db):
        stock = _seed_stock(db, ticker="CRM")
        db.add(
            Holding(
                stock_id=stock.id,
                quantity=4.0,
                avg_buy_price=90.0,
                buy_date=date(2025, 1, 1),
                broker=Broker.VESTED,
            )
        )
        db.commit()
        _seed_snapshot(db)

        r = client.post(
            "/api/actions/CRM/execute",
            json={
                "action": "sell",
                "bucket": "quality_momentum",
                "country": "US",
                "actual_fill_price": 110.0,
                "qty": 4.0,
                "lesson": "Respect the rules and take the full exit when conviction breaks.",
            },
        )
        assert r.status_code == 201
        assert db.execute(select(Holding).where(Holding.stock_id == stock.id)).scalar_one_or_none() is None

        journal = db.execute(select(TradeJournalEntry).where(TradeJournalEntry.stock_id == stock.id)).scalar_one()
        assert journal.action_type == ActionType.SELL
        assert journal.exit_learning is not None


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

class TestStocks:
    def test_unknown_ticker_404(self, client):
        r = client.get("/api/stocks/UNKNOWN")
        assert r.status_code == 404

    def test_known_ticker_returns_detail(self, client, db):
        _seed_stock(db, ticker="MSFT")
        r = client.get("/api/stocks/MSFT")
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "MSFT"
        assert data["sector"] == "Technology"

    def test_scores_empty_without_snapshot(self, client, db):
        _seed_stock(db, ticker="GOOG")
        r = client.get("/api/stocks/GOOG")
        assert r.json()["scores"] == []

    def test_case_insensitive_ticker(self, client, db):
        _seed_stock(db, ticker="AMZN")
        r = client.get("/api/stocks/amzn")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_empty_portfolio(self, client):
        r = client.get("/api/portfolio")
        assert r.status_code == 200
        assert r.json()["holdings"] == []

    def test_add_holding(self, client, db):
        _seed_stock(db, ticker="INFY", country=Country.INDIA)
        r = client.post("/api/portfolio/holdings", json={
            "ticker": "INFY",
            "country": "IN",
            "qty": 10,
            "avg_buy_price": 1500.0,
        })
        assert r.status_code == 201
        assert r.json()["ticker"] == "INFY"

    def test_add_holding_auto_creates_stock(self, client):
        r = client.post("/api/portfolio/holdings", json={
            "ticker": "NEWCO",
            "country": "US",
            "qty": 5,
            "avg_buy_price": 200.0,
        })
        assert r.status_code == 201

    def test_update_holding(self, client, db):
        stock = _seed_stock(db, ticker="TCS", country=Country.INDIA)
        holding = Holding(
            stock_id=stock.id, quantity=5.0, avg_buy_price=3000.0,
            buy_date=date(2025, 1, 1), broker=Broker.KITE,
        )
        db.add(holding)
        db.commit()
        r = client.put(f"/api/portfolio/holdings/{holding.id}", json={"qty": 10.0})
        assert r.status_code == 200
        assert r.json()["qty"] == 10.0

    def test_delete_holding(self, client, db):
        stock = _seed_stock(db, ticker="WIPRO", country=Country.INDIA)
        holding = Holding(
            stock_id=stock.id, quantity=20.0, avg_buy_price=500.0,
            buy_date=date(2025, 6, 1), broker=Broker.KITE,
        )
        db.add(holding)
        db.commit()
        r = client.delete(f"/api/portfolio/holdings/{holding.id}")
        assert r.status_code == 204

    def test_summary_returns_totals(self, client, db):
        stock = _seed_stock(db, ticker="RELIANCE", country=Country.INDIA)
        db.add(Holding(
            stock_id=stock.id, quantity=5.0, avg_buy_price=2000.0,
            buy_date=date(2025, 1, 1), broker=Broker.KITE,
        ))
        db.commit()
        r = client.get("/api/portfolio/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["total_cost"] == 10000.0

    def test_summary_includes_sector_allocation(self, client, db):
        stock = _seed_stock(db, ticker="MSFT", sector="Technology")
        db.add(
            Holding(
                stock_id=stock.id,
                quantity=2.0,
                avg_buy_price=100.0,
                buy_date=date(2025, 1, 1),
                broker=Broker.VESTED,
            )
        )
        db.commit()

        r = client.get("/api/portfolio")
        assert r.status_code == 200
        assert r.json()["summary"]["sector_allocation"][0]["sector"] == "Technology"


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

class TestJournal:
    def test_empty_journal(self, client):
        r = client.get("/api/journal")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_entry(self, client, db):
        _seed_stock(db, ticker="AAPL")
        r = client.post("/api/journal", json={
            "trade_date": "2026-04-07",
            "ticker": "AAPL",
            "country": "US",
            "action": "buy",
            "actual_fill_price": 175.0,
            "qty": 2.0,
        })
        assert r.status_code == 201
        assert r.json()["ticker"] == "AAPL"

    def test_update_entry_lesson(self, client, db):
        entry = TradeJournalEntry(
            action_type=ActionType.SELL, action_date=date(2026, 4, 7), executed=True,
        )
        db.add(entry)
        db.commit()
        r = client.put(f"/api/journal/{entry.id}", json={"lesson": "Sold too early"})
        assert r.status_code == 200
        assert r.json()["lesson"] == "Sold too early"

    def test_monthly_review_empty(self, client):
        r = client.get("/api/journal/review")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_skip_month_creates_entry(self, client):
        r = client.post("/api/actions/skip-month", json={"reason": "Waiting for clarity"})
        assert r.status_code == 201

    def test_create_exit_entry_requires_lesson(self, client, db):
        _seed_stock(db, ticker="META")
        r = client.post(
            "/api/journal",
            json={
                "trade_date": "2026-04-07",
                "ticker": "META",
                "country": "US",
                "action": "sell",
                "actual_fill_price": 400.0,
                "qty": 1.0,
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# News & Shock
# ---------------------------------------------------------------------------

class TestNews:
    def test_empty_news_feed(self, client):
        r = client.get("/api/news")
        assert r.status_code == 200
        assert r.json()["articles"] == []

    def test_news_with_items(self, client, db):
        stock = _seed_stock(db)
        db.add(NewsItem(
            stream=NewsStream.STOCK,
            stock_id=stock.id,
            source="Reuters",
            headline="Apple reports record quarter",
            url="https://example.com/1",
            published_at=datetime.now(tz=timezone.utc),
            category=NewsCategory.EARNINGS,
            sentiment_label=SentimentLabel.POSITIVE,
            sentiment_score=0.7,
        ))
        db.commit()
        r = client.get(f"/api/news?ticker=AAPL")
        assert r.status_code == 200
        assert len(r.json()["articles"]) == 1

    def test_shock_status_no_events(self, client):
        r = client.get("/api/shock")
        assert r.status_code == 200
        assert r.json()["active"] is False

    def test_shock_status_with_red_event(self, client, db):
        db.add(ShockEvent(
            triggered_at=datetime.now(tz=timezone.utc),
            banner=ShockBanner.RED,
            headline="War declared",
            source="AP",
            matched_keywords=["war"],
        ))
        db.commit()
        r = client.get("/api/shock")
        assert r.json()["active"] is True

    def test_dismiss_shock(self, client, db):
        event = ShockEvent(
            triggered_at=datetime.now(tz=timezone.utc),
            banner=ShockBanner.RED,
            headline="War declared",
            source="AP",
            matched_keywords=["war"],
        )
        db.add(event)
        db.commit()
        r = client.post(f"/api/shock/{event.id}/dismiss")
        assert r.status_code == 200
        assert "dismissed_until" in r.json()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    def test_get_defaults(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert data["picks_per_bucket"] == 10
        assert data["rebalance_day"] == 7

    def test_update_picks(self, client):
        r = client.put("/api/settings", json={"picks_per_bucket": 15})
        assert r.status_code == 200
        assert r.json()["picks_per_bucket"] == 15

    def test_update_persists(self, client):
        client.put("/api/settings", json={"telegram_enabled": True})
        r = client.get("/api/settings")
        assert r.json()["telegram_enabled"] is True

    def test_update_bucket_allocations(self, client):
        r = client.put("/api/settings", json={
            "bucket_allocations": [
                {"bucket": "quality_value", "allocation_pct": 70.0},
                {"bucket": "quality_momentum", "allocation_pct": 30.0},
                {"bucket": "momentum", "allocation_pct": 0.0},
                {"bucket": "dividend_growth", "allocation_pct": 0.0},
            ]
        })
        assert r.status_code == 200
        allocs = {a["bucket"]: a["allocation_pct"] for a in r.json()["bucket_allocations"]}
        assert allocs["quality_value"] == 70.0


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    def test_status_no_snapshot(self, client):
        r = client.get("/api/pipeline/status")
        assert r.status_code == 200
        assert r.json()["last_run_date"] is None
        assert r.json()["running"] is False

    def test_trigger_run_accepted(self, client):
        # Don't actually run the pipeline — just verify the endpoint accepts the request
        with patch("api.routers.pipeline._run_pipeline_bg"):
            r = client.post("/api/pipeline/run")
        assert r.status_code == 202
        assert r.json()["status"] in ("started", "already_running")

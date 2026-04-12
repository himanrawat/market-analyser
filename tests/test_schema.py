"""Smoke test: schema creates, basic inserts round-trip correctly."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from pipeline.db import models
from pipeline.db.base import Base
from pipeline.db.enums import (
    ActionType,
    Bucket,
    Country,
    IndexName,
    MacroRegime,
    NewsStream,
    ShockBanner,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


def test_all_tables_created(session):
    from sqlalchemy import inspect

    inspector = inspect(session.bind)
    expected = {
        "stocks",
        "universe_memberships",
        "prices",
        "fundamentals",
        "news_items",
        "events",
        "macro_snapshots",
        "holdings",
        "rebalance_snapshots",
        "scores",
        "trade_journal",
        "shock_events",
        "settings_kv",
    }
    assert expected.issubset(set(inspector.get_table_names()))


def test_stock_and_price_roundtrip(session):
    stock = models.Stock(
        ticker="RELIANCE",
        country=Country.INDIA,
        name="Reliance Industries",
        sector="Energy",
        currency="INR",
        market_cap=1_800_000_00_00_000.0,
        listing_date=date(1977, 11, 29),
    )
    session.add(stock)
    session.flush()

    price = models.Price(
        stock_id=stock.id,
        date=date(2026, 4, 10),
        open=2900.0,
        high=2950.0,
        low=2890.0,
        close=2930.0,
        adj_close=2930.0,
        volume=5_000_000,
    )
    session.add(price)
    session.commit()

    fetched = session.execute(
        select(models.Stock).where(models.Stock.ticker == "RELIANCE")
    ).scalar_one()
    assert fetched.country == Country.INDIA
    assert fetched.prices[0].close == 2930.0


def test_rebalance_snapshot_with_scores(session):
    stock = models.Stock(
        ticker="AAPL",
        country=Country.US,
        name="Apple Inc.",
        sector="Technology",
        currency="USD",
    )
    session.add(stock)
    session.flush()

    snap = models.RebalanceSnapshot(
        run_date=date(2026, 4, 6),
        run_started_at=datetime(2026, 4, 6, 20, 0),
        macro_regime=MacroRegime.RISK_ON,
        shock_regime=False,
        universe_size_raw=1000,
        universe_size_filtered=312,
        config_snapshot={"picks_per_bucket": 10},
    )
    session.add(snap)
    session.flush()

    score = models.Score(
        snapshot_id=snap.id,
        stock_id=stock.id,
        bucket=Bucket.QUALITY_MOMENTUM,
        score=87.5,
        qualified=True,
        rank=1,
        factor_scores={"roe": 15, "momentum": 20, "pe_vs_sector": 14},
        disqualifiers=None,
    )
    session.add(score)
    session.commit()

    fetched_snap = session.get(models.RebalanceSnapshot, snap.id)
    assert len(fetched_snap.scores) == 1
    assert fetched_snap.scores[0].score == 87.5
    assert fetched_snap.scores[0].factor_scores["roe"] == 15


def test_news_and_shock(session):
    news = models.NewsItem(
        stream=NewsStream.GENERAL,
        source="FMP",
        headline="Breaking: unscheduled Fed rate decision",
        url="https://example.com/news/1",
        published_at=datetime(2026, 4, 11, 14, 30),
        matched_keywords=["unscheduled Fed", "emergency rate"],
    )
    session.add(news)

    shock = models.ShockEvent(
        triggered_at=datetime(2026, 4, 11, 14, 45),
        banner=ShockBanner.RED,
        headline="Breaking: unscheduled Fed rate decision",
        source="FMP",
        matched_keywords=["unscheduled Fed", "emergency rate"],
        india_vix_at_trigger=22.4,
        us_vix_at_trigger=28.1,
        india_vix_change_pct=23.0,
        us_vix_change_pct=25.0,
    )
    session.add(shock)
    session.commit()

    assert session.execute(select(models.NewsItem)).scalar_one().matched_keywords == [
        "unscheduled Fed",
        "emergency rate",
    ]
    assert session.execute(select(models.ShockEvent)).scalar_one().banner == ShockBanner.RED


def test_universe_membership_history(session):
    m1 = models.UniverseMembership(
        index_name=IndexName.NIFTY_500,
        ticker="ZOMATO",
        country=Country.INDIA,
        added_date=date(2022, 10, 1),
        removed_date=None,
    )
    m2 = models.UniverseMembership(
        index_name=IndexName.NIFTY_500,
        ticker="YESBANK",
        country=Country.INDIA,
        added_date=date(2018, 1, 1),
        removed_date=date(2020, 6, 1),
    )
    session.add_all([m1, m2])
    session.commit()

    active = session.execute(
        select(models.UniverseMembership).where(
            models.UniverseMembership.removed_date.is_(None)
        )
    ).scalars().all()
    assert len(active) == 1
    assert active[0].ticker == "ZOMATO"


def test_trade_journal_skip_month(session):
    entry = models.TradeJournalEntry(
        action_type=ActionType.SKIP_MONTH,
        action_date=date(2026, 4, 7),
        user_notes="Shock regime active — deliberately skipping this month.",
        executed=True,
    )
    session.add(entry)
    session.commit()

    fetched = session.execute(select(models.TradeJournalEntry)).scalar_one()
    assert fetched.action_type == ActionType.SKIP_MONTH
    assert fetched.executed is True

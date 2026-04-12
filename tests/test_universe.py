"""Tests for universe loader and filter."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from pipeline.db.enums import Country, IndexName
from pipeline.providers.dto import UniverseConstituent
from pipeline.universe.filter import (
    MIN_AVG_VOLUME_USD,
    MIN_MARKET_CAP_USD,
    FilterResult,
    UniverseFilter,
)
from pipeline.universe.sources import fetch_sp500


# ---------------------------------------------------------------------------
# UniverseFilter — unit tests with in-memory DB
# ---------------------------------------------------------------------------


def _make_stock(
    ticker="AAPL",
    country=Country.US,
    market_cap=3_000_000_000_000.0,
    listing_date=None,
    is_suspended=False,
    in_fno_ban=False,
):
    s = MagicMock()
    s.ticker = ticker
    s.country = country
    s.market_cap = market_cap
    s.listing_date = listing_date or date(2010, 1, 1)
    s.is_suspended = is_suspended
    s.in_fno_ban = in_fno_ban
    s.id = hash(ticker)
    return s


def _make_prices(close=150.0, volume=60_000_000, n=60):
    prices = []
    for i in range(n):
        p = MagicMock()
        p.close = close
        p.volume = volume
        prices.append(p)
    return prices


class TestUniverseFilter:
    @pytest.fixture()
    def uf(self):
        return UniverseFilter(as_of=date(2026, 4, 10))

    def test_passing_stock(self, uf):
        stock = _make_stock()
        prices = _make_prices(close=150.0, volume=80_000_000)  # $12B/day
        result = uf._check(stock, prices)
        assert result is None

    def test_suspended_fails(self, uf):
        stock = _make_stock(is_suspended=True)
        assert uf._check(stock, []) == "suspended"

    def test_fno_ban_fails(self, uf):
        stock = _make_stock(in_fno_ban=True)
        assert uf._check(stock, []) == "fno_ban"

    def test_listed_too_recently_fails(self, uf):
        # Listed 1 year ago — below 3-year minimum
        stock = _make_stock(listing_date=date(2025, 4, 1))
        result = uf._check(stock, _make_prices())
        assert result is not None
        assert "listed_too_recently" in result

    def test_market_cap_too_small_fails(self, uf):
        stock = _make_stock(market_cap=500_000_000)  # $500M < $2B
        result = uf._check(stock, _make_prices())
        assert result is not None
        assert "market_cap_too_small" in result

    def test_low_volume_fails(self, uf):
        # close=10, volume=500_000 → $5M/day < $10M threshold
        stock = _make_stock()
        prices = _make_prices(close=10.0, volume=500_000)
        result = uf._check(stock, prices)
        assert result is not None
        assert "low_avg_volume" in result

    def test_no_prices_passes_through(self, uf):
        """Stocks with no price history yet get a pass — they'll be skipped in scoring."""
        stock = _make_stock()
        assert uf._check(stock, []) is None

    def test_unknown_listing_date_passes(self, uf):
        """If listing_date is None, we give benefit of the doubt."""
        stock = _make_stock(listing_date=None)
        stock.listing_date = None
        result = uf._check(stock, _make_prices())
        assert result is None

    def test_run_splits_passed_and_failed(self, uf):
        stocks = {
            ("AAPL", Country.US): _make_stock("AAPL"),
            ("JUNK", Country.US): _make_stock("JUNK", market_cap=100_000),
            ("SUSP", Country.US): _make_stock("SUSP", is_suspended=True),
        }
        prices = {
            hash("AAPL"): _make_prices(close=150.0, volume=80_000_000),
            hash("JUNK"): _make_prices(),
            hash("SUSP"): _make_prices(),
        }
        with (
            patch.object(uf, "_load_stocks", return_value=stocks),
            patch.object(uf, "_load_recent_prices", return_value=prices),
        ):
            result = uf.run([("AAPL", Country.US), ("JUNK", Country.US), ("SUSP", Country.US)])

        assert ("AAPL", Country.US) in result.passed
        assert "JUNK" in result.failed
        assert "SUSP" in result.failed
        assert result.pass_count == 1
        assert result.fail_count == 2


# ---------------------------------------------------------------------------
# sources — unit tests with mocked network
# ---------------------------------------------------------------------------


def _make_sp500_df():
    import pandas as pd
    return pd.DataFrame(
        {
            "Symbol": ["AAPL", "MSFT", "BRK.B"],
            "Security": ["Apple Inc.", "Microsoft Corp.", "Berkshire Hathaway B"],
            "GICS Sector": ["Technology", "Technology", "Financials"],
            "GICS Sub-Industry": ["Consumer Electronics", "Systems Software", "Insurance"],
        }
    )


class TestSources:
    @patch("pandas.read_html")
    def test_fetch_sp500_normalizes_brk(self, mock_read_html):
        mock_read_html.return_value = [_make_sp500_df()]
        constituents = fetch_sp500()
        tickers = [c.ticker for c in constituents]
        assert "BRK-B" in tickers   # dot replaced with dash
        assert "BRK.B" not in tickers

    @patch("pandas.read_html")
    def test_fetch_sp500_returns_correct_country(self, mock_read_html):
        mock_read_html.return_value = [_make_sp500_df()]
        constituents = fetch_sp500()
        assert all(c.country == Country.US for c in constituents)
        assert all(c.index_name == IndexName.SP_500 for c in constituents)

    @patch("pandas.read_html")
    def test_fetch_sp500_skips_empty_tickers(self, mock_read_html):
        import pandas as pd
        df = _make_sp500_df()
        df.loc[len(df)] = {"Symbol": "", "Security": "Ghost", "GICS Sector": "", "GICS Sub-Industry": ""}
        mock_read_html.return_value = [df]
        constituents = fetch_sp500()
        assert all(c.ticker for c in constituents)


# ---------------------------------------------------------------------------
# UniverseLoader — integration-style with in-memory SQLite
# ---------------------------------------------------------------------------


class TestUniverseLoader:
    @pytest.fixture()
    def in_memory_session(self, monkeypatch):
        """Point the loader at an in-memory SQLite DB."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from pipeline.db.base import Base
        from pipeline.db import models  # noqa: F401

        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)

        import contextlib
        @contextlib.contextmanager
        def fake_get_session():
            with Session() as s:
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise

        monkeypatch.setattr("pipeline.universe.loader.get_session", fake_get_session)
        monkeypatch.setattr("pipeline.universe.filter.get_session", fake_get_session)
        return fake_get_session

    def test_sync_inserts_new_stocks(self, in_memory_session):
        from pipeline.universe.loader import UniverseLoader

        constituents = [
            UniverseConstituent(
                index_name=IndexName.SP_500,
                ticker="AAPL",
                country=Country.US,
                name="Apple Inc.",
                sector="Technology",
                as_of=date.today(),
            ),
            UniverseConstituent(
                index_name=IndexName.SP_500,
                ticker="MSFT",
                country=Country.US,
                name="Microsoft Corp.",
                sector="Technology",
                as_of=date.today(),
            ),
        ]

        mock_dp = MagicMock()
        loader = UniverseLoader(data_provider=mock_dp)

        with (
            patch("pipeline.universe.loader.fetch_constituents", return_value=constituents),
            patch.object(loader, "_backfill_missing_profiles"),
        ):
            result = loader.refresh([IndexName.SP_500])

        assert result[IndexName.SP_500] == 2

    def test_sync_marks_removed_tickers(self, in_memory_session):
        """A ticker present in DB but missing from new fetch gets removed_date set."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from pipeline.db.base import Base
        from pipeline.db import models as m

        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)

        import contextlib
        @contextlib.contextmanager
        def session_ctx():
            with Session() as s:
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise

        # Seed an existing membership
        with session_ctx() as s:
            s.add(m.Stock(ticker="OLD", country=Country.US, name="Old Corp", currency="USD"))
            s.add(m.UniverseMembership(
                index_name=IndexName.SP_500, ticker="OLD",
                country=Country.US, added_date=date(2025, 1, 1)
            ))

        from unittest.mock import patch as mpatch
        import pipeline.universe.loader as loader_mod

        with mpatch.object(loader_mod, "get_session", session_ctx):
            from pipeline.universe.loader import UniverseLoader
            loader = UniverseLoader(data_provider=MagicMock())
            new_constituents = [
                UniverseConstituent(
                    index_name=IndexName.SP_500,
                    ticker="AAPL",
                    country=Country.US,
                    name="Apple Inc.",
                    sector="Technology",
                    as_of=date.today(),
                )
            ]
            with (
                mpatch.object(loader_mod, "fetch_constituents", return_value=new_constituents),
                mpatch.object(loader, "_backfill_missing_profiles"),
            ):
                loader.refresh([IndexName.SP_500])

        with session_ctx() as s:
            from sqlalchemy import select
            mem = s.execute(
                select(m.UniverseMembership).where(m.UniverseMembership.ticker == "OLD")
            ).scalar_one()
            assert mem.removed_date == date.today()

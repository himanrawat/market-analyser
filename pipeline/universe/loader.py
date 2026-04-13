"""UniverseLoader: fetches constituent lists, syncs to DB, pulls profiles.

Responsibilities:
1. For each target index, call the appropriate source fetcher.
2. Upsert into `stocks` (canonical row) and `universe_memberships` (history).
3. For any new stock (not yet in DB), fetch its profile via DataProvider.
4. Mark stale memberships (removed from index) with a removed_date.

Called by the pipeline runner before filtering and scoring. The quarterly
cadence (F-1.1) is enforced by the scheduler — UniverseLoader itself is
idempotent and can be re-run at any time.
"""
from __future__ import annotations

from datetime import date

from loguru import logger
from sqlalchemy import select

from pipeline.db.base import get_session
from pipeline.db.enums import Country, IndexName
from pipeline.db.models import Stock, UniverseMembership
from pipeline.providers.dto import UniverseConstituent
from pipeline.providers.registry import DataProvider, get_data_provider
from pipeline.universe.sources import fetch_constituents

# Phase 1: India market only. SP_500 will be re-added in Phase 2 (US market).
DEFAULT_INDEXES = [IndexName.NIFTY_500]


class UniverseLoader:
    """Loads and syncs constituent lists into the database."""

    def __init__(self, data_provider: DataProvider | None = None) -> None:
        self.dp = data_provider or get_data_provider()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(self, indexes: list[IndexName] | None = None) -> dict[str, int]:
        """Fetch constituents for each index and sync to DB.

        Returns a dict of {index_name: upserted_count}.
        """
        targets = indexes or DEFAULT_INDEXES
        results: dict[str, int] = {}
        for idx in targets:
            try:
                constituents = fetch_constituents(idx)
                count = self._sync_index(idx, constituents)
                results[idx] = count
            except Exception as exc:
                logger.error(f"Universe refresh failed for {idx}: {exc}")
                results[idx] = 0
        return results

    def get_active_tickers(
        self, country: Country | None = None, index: IndexName | None = None
    ) -> list[tuple[str, Country]]:
        """Return (ticker, country) for all active stocks in the universe.
        Optionally filter by country or by membership in a specific index."""
        with get_session() as session:
            if index is not None:
                # Join through universe_memberships
                stmt = (
                    select(Stock.ticker, Stock.country)
                    .join(
                        UniverseMembership,
                        (UniverseMembership.ticker == Stock.ticker)
                        & (UniverseMembership.country == Stock.country),
                    )
                    .where(
                        UniverseMembership.index_name == index,
                        UniverseMembership.removed_date.is_(None),
                        Stock.is_active.is_(True),
                    )
                )
            else:
                stmt = select(Stock.ticker, Stock.country).where(Stock.is_active.is_(True))

            if country is not None:
                stmt = stmt.where(Stock.country == country)

            rows = session.execute(stmt).all()
        return [(r.ticker, r.country) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sync_index(
        self, index_name: IndexName, constituents: list[UniverseConstituent]
    ) -> int:
        """Upsert stocks + memberships, mark removed tickers, return upsert count."""
        today = date.today()
        incoming_tickers = {(c.ticker, c.country) for c in constituents}

        with get_session() as session:
            # 1. Mark previously-active members that are no longer in the list
            active_memberships = session.execute(
                select(UniverseMembership).where(
                    UniverseMembership.index_name == index_name,
                    UniverseMembership.removed_date.is_(None),
                )
            ).scalars().all()

            for mem in active_memberships:
                if (mem.ticker, mem.country) not in incoming_tickers:
                    mem.removed_date = today
                    logger.debug(f"Marked {mem.ticker} removed from {index_name}")

            # 2. Upsert each constituent
            upserted = 0
            for c in constituents:
                self._upsert_stock(session, c)
                self._upsert_membership(session, index_name, c, today)
                upserted += 1

            session.flush()

        # 3. Backfill profiles for stocks that have no name yet (new additions)
        self._backfill_missing_profiles(index_name)

        logger.info(f"{index_name}: {upserted} stocks synced")
        return upserted

    def _upsert_stock(self, session, c: UniverseConstituent) -> Stock:
        """Insert stock if not exists, update sector/name if it changed."""
        existing = session.execute(
            select(Stock).where(Stock.ticker == c.ticker, Stock.country == c.country)
        ).scalar_one_or_none()

        if existing is None:
            stock = Stock(
                ticker=c.ticker,
                country=c.country,
                name=c.name,
                sector=c.sector,
                industry=c.industry,
                currency="INR" if c.country == Country.INDIA else "USD",
                is_active=True,
                isin=c.isin,
                nse_symbol=c.nse_symbol,
                bse_symbol=c.bse_symbol,
                bse_scripcode=c.bse_scripcode,
            )
            session.add(stock)
            logger.debug(f"New stock: {c.ticker} ({c.country})")
        else:
            # Update mutable fields that can change over time
            if c.name and c.name != existing.name:
                existing.name = c.name
            if c.sector and c.sector != existing.sector:
                existing.sector = c.sector
            if c.industry and c.industry != existing.industry:
                existing.industry = c.industry
            if c.isin and c.isin != existing.isin:
                existing.isin = c.isin
            if c.nse_symbol and c.nse_symbol != existing.nse_symbol:
                existing.nse_symbol = c.nse_symbol
            if c.bse_symbol and c.bse_symbol != existing.bse_symbol:
                existing.bse_symbol = c.bse_symbol
            if c.bse_scripcode and c.bse_scripcode != existing.bse_scripcode:
                existing.bse_scripcode = c.bse_scripcode
            existing.is_active = True
            stock = existing
        return stock

    def _upsert_membership(
        self,
        session,
        index_name: IndexName,
        c: UniverseConstituent,
        today: date,
    ) -> None:
        """Ensure an open membership row exists for this ticker+index."""
        existing = session.execute(
            select(UniverseMembership).where(
                UniverseMembership.index_name == index_name,
                UniverseMembership.ticker == c.ticker,
                UniverseMembership.country == c.country,
                UniverseMembership.removed_date.is_(None),
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                UniverseMembership(
                    index_name=index_name,
                    ticker=c.ticker,
                    country=c.country,
                    added_date=today,
                )
            )

    def _backfill_missing_profiles(self, index_name: IndexName) -> None:
        """For stocks where market_cap or description is missing, fetch from provider.
        This only runs for new additions — bulk profile fetch is rate-limit safe
        because yfinance doesn't have strict rate limits."""
        with get_session() as session:
            stocks_missing_cap = session.execute(
                select(Stock)
                .join(
                    UniverseMembership,
                    (UniverseMembership.ticker == Stock.ticker)
                    & (UniverseMembership.country == Stock.country),
                )
                .where(
                    UniverseMembership.index_name == index_name,
                    UniverseMembership.removed_date.is_(None),
                    Stock.market_cap.is_(None),
                )
                .limit(50)  # cap per run to avoid rate limits on first load
            ).scalars().all()

        if not stocks_missing_cap:
            return

        logger.info(
            f"Backfilling profiles for {len(stocks_missing_cap)} new stocks in {index_name}…"
        )
        for stock in stocks_missing_cap:
            try:
                profile = self.dp.fundamentals.get_profile(
                    stock.ticker, stock.country
                )
                with get_session() as session:
                    s = session.get(Stock, stock.id)
                    if s:
                        s.market_cap = profile.market_cap
                        s.listing_date = profile.listing_date
                        s.description = profile.description
                        if profile.sector and not s.sector:
                            s.sector = profile.sector
                        if profile.industry and not s.industry:
                            s.industry = profile.industry
                        if profile.currency:
                            s.currency = profile.currency
                        if profile.isin and not s.isin:
                            s.isin = profile.isin
                        if profile.nse_symbol and not s.nse_symbol:
                            s.nse_symbol = profile.nse_symbol
                        if profile.bse_symbol and not s.bse_symbol:
                            s.bse_symbol = profile.bse_symbol
                        if profile.bse_scripcode and not s.bse_scripcode:
                            s.bse_scripcode = profile.bse_scripcode
            except Exception as exc:
                logger.warning(f"Profile fetch failed for {stock.ticker}: {exc}")

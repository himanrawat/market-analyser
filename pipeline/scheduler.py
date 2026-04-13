"""Monthly pipeline orchestrator (F-12.4)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from loguru import logger
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pipeline.config import settings
from pipeline.db import init_db
from pipeline.db.base import get_session
from pipeline.db.enums import Country, EventType, IndexName, MacroRegime, NewsCategory, NewsStream
from pipeline.db.models import (
    Event,
    Fundamental,
    IndiaDerivatives,
    IndiaMarketBreadth,
    MacroSnapshot,
    NewsItem,
    Price,
    RebalanceSnapshot,
    Score,
    ShockEvent,
    Stock,
)
from pipeline.importers import fetch_nse_official_batch
from pipeline.logging_setup import configure_logging
from pipeline.news.sentiment import SentimentScorer
from pipeline.news.shock import ShockDetector
from pipeline.notify.telegram import TelegramNotifier
from pipeline.portfolio.diff import DiffResult, PortfolioDiff
from pipeline.portfolio.planner import CapitalPlanner
from pipeline.providers.dto import EventRecord
from pipeline.providers.errors import DataProviderError, SymbolNotFoundError
from pipeline.providers.fmp_provider import FMPProvider
from pipeline.providers.registry import get_data_provider
from pipeline.scoring.engine import ScoringEngine
from pipeline.scoring.guardrails import Guardrails, compute_macro_regime
from pipeline.universe.filter import UniverseFilter
from pipeline.universe.loader import UniverseLoader

PRICE_BACKFILL_DAYS = 365 * 3 + 30
GENERAL_NEWS_DAYS = 30
EVENT_LOOKAHEAD_DAYS = 120
MACRO_HISTORY_DAYS = 400
OFFICIAL_INDIA_BOOTSTRAP_TICKERS = ("RELIANCE", "TCS", "INFY", "ITC", "HINDUNILVR")
PIPELINE_COUNTRY = Country.INDIA
PIPELINE_INDEX = IndexName.NIFTY_500


@dataclass(frozen=True)
class MacroContext:
    india_vix: float | None
    india_vix_prev: float | None
    us_vix: float | None
    us_vix_prev: float | None


def run_pipeline(
    as_of: date | None = None,
    fresh_capital: float = 0.0,
    picks_per_bucket: int = 10,
) -> DiffResult:
    """Execute the full monthly rebalance pipeline and persist a snapshot."""
    run_date = as_of or date.today()
    run_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    configure_logging()
    notifier = TelegramNotifier()

    logger.info("=" * 60)
    logger.info(f"Pipeline run starting — {run_date}")
    logger.info("=" * 60)

    try:
        init_db()

        logger.info("Step 1/9: Refreshing universe...")
        loader = UniverseLoader()
        loader.refresh(indexes=[PIPELINE_INDEX])
        universe_tickers = loader.get_active_tickers(
            country=PIPELINE_COUNTRY,
            index=PIPELINE_INDEX,
        )
        logger.info(
            f"Active universe loaded: {len(universe_tickers)} stocks "
            f"({PIPELINE_COUNTRY.value}, {PIPELINE_INDEX.value})"
        )

        logger.info("Step 2/9: Refreshing official India fundamentals lane...")
        _refresh_official_india_lane(universe_tickers)

        logger.info("Step 3/9: Pulling macro snapshot...")
        provider = get_data_provider()
        macro_context = _pull_macro_snapshot(provider, run_date)

        logger.info("Step 4/9: Syncing prices, fundamentals, events, and news...")
        _pull_market_data(provider, universe_tickers, run_date, macro_context)

        logger.info("Step 5/9: Applying universe filters...")
        filtered = UniverseFilter(as_of=run_date).run(universe_tickers)

        logger.info("Step 6/9: Running scoring engine...")
        engine = ScoringEngine()
        score_outputs = engine.run(filtered.passed, as_of=run_date)

        macro_regime = _macro_regime_for_date(run_date)
        shock_regime = ShockDetector().active_shock(within_days=14) is not None

        logger.info("Step 7/9: Applying guardrails...")
        guardrail_results = Guardrails(
            picks_per_bucket=picks_per_bucket,
            as_of=run_date,
        ).apply(
            score_outputs,
            macro_regime=macro_regime,
            shock_regime=shock_regime,
        )

        logger.info("Step 8/9: Computing portfolio diff and deployment plan...")
        diff_result = PortfolioDiff(as_of=run_date).run(guardrail_results)
        plan = CapitalPlanner().plan(
            diff_result.buys + diff_result.adds,
            fresh_capital=fresh_capital,
        )
        logger.info(
            f"Capital plan: total={plan.total_available:.0f}, "
            f"deployed={sum(plan.action_amounts.values()):.0f}, "
            f"undeployed={plan.undeployed:.0f}"
        )

        logger.info("Step 9/9: Persisting snapshot...")
        _persist_snapshot(
            diff_result=diff_result,
            guardrail_results=guardrail_results,
            run_date=run_date,
            run_started_at=run_started_at,
            picks_per_bucket=picks_per_bucket,
            universe_size_raw=len(universe_tickers),
            universe_size_filtered=filtered.pass_count,
        )

        notifier.send_monthly_digest(diff_result)

        logger.info("=" * 60)
        logger.info(
            f"Pipeline complete — "
            f"{len(diff_result.buys)} BUY, "
            f"{len(diff_result.sells)} SELL, "
            f"{len(diff_result.adds)} ADD, "
            f"{len(diff_result.holds)} HOLD"
        )
        logger.info("=" * 60)
        return diff_result

    except Exception as exc:
        logger.exception(f"Pipeline failed: {exc}")
        notifier.send_text(
            f"❌ <b>Pipeline run FAILED</b> — {run_date}\n\n"
            f"Error: {type(exc).__name__}: {exc}\n\n"
            "Check server logs for full traceback."
        )
        raise


def _refresh_official_india_lane(tickers: list[tuple[str, Country]]) -> None:
    if not settings.official_india_auto_fetch_enabled:
        logger.debug("Official India auto-fetch disabled — skipping")
        return

    batch_size = max(int(settings.official_india_auto_fetch_batch_size), 0)
    if batch_size == 0:
        logger.debug("Official India auto-fetch batch size is 0 — skipping")
        return

    candidates = _select_official_india_batch_candidates(
        tickers,
        batch_size=batch_size,
        data_dir=settings.official_india_data_dir,
    )
    if not candidates:
        logger.debug("Official India hybrid lane already warm for the current batch")
        return

    logger.info(
        f"Fetching official India data for {len(candidates)} tickers: {', '.join(candidates)}"
    )
    try:
        result = fetch_nse_official_batch(
            tickers=candidates,
            limit=max(int(settings.official_india_auto_fetch_limit), 1),
            statement_scope=settings.official_india_auto_fetch_statement_scope,
            output_dir=settings.official_india_data_dir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Official India batch fetch failed before import: {exc}")
        return

    if result.completed:
        logger.info(
            f"Official India batch fetch complete — {len(result.completed)} succeeded, "
            f"{len(result.failed)} failed"
        )
    for ticker, error in result.failed:
        logger.warning(f"Official India batch fetch failed for {ticker}: {error}")


def _select_official_india_batch_candidates(
    tickers: list[tuple[str, Country]],
    *,
    batch_size: int,
    data_dir: Path,
) -> list[str]:
    india_tickers = [ticker for ticker, country in tickers if country == Country.INDIA]
    if not india_tickers or batch_size <= 0:
        return []

    ordered: list[str] = []
    seen: set[str] = set()
    for ticker in OFFICIAL_INDIA_BOOTSTRAP_TICKERS:
        if ticker in india_tickers and ticker not in seen:
            ordered.append(ticker)
            seen.add(ticker)
    for ticker in india_tickers:
        if ticker not in seen:
            ordered.append(ticker)
            seen.add(ticker)

    candidates: list[str] = []
    for ticker in ordered:
        if _needs_official_india_fetch(ticker, data_dir):
            candidates.append(ticker)
        if len(candidates) >= batch_size:
            break
    return candidates


def _needs_official_india_fetch(ticker: str, data_dir: Path) -> bool:
    return not (
        _official_india_kind_exists(data_dir, ticker, "financials")
        and _official_india_kind_exists(data_dir, ticker, "shareholding")
    )


def _official_india_kind_exists(data_dir: Path, ticker: str, kind: str) -> bool:
    for path in (
        data_dir / "nse" / kind / f"{ticker}.json",
        data_dir / "nse" / kind / f"{ticker}.csv",
        data_dir / "bse" / kind / f"{ticker}.json",
        data_dir / "bse" / kind / f"{ticker}.csv",
        data_dir / kind / f"{ticker}.json",
        data_dir / kind / f"{ticker}.csv",
    ):
        if path.exists():
            return True
    return False


def _pull_market_data(provider, tickers, as_of: date, macro_context: MacroContext) -> None:
    stock_lookup = _stock_lookup()
    skipped: list[str] = []

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]Syncing market data[/bold cyan]"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("• [yellow]{task.fields[current]}[/yellow]"),
        refresh_per_second=4,
    )

    with progress:
        task = progress.add_task("sync", total=len(tickers), current="")
        for ticker, country in tickers:
            progress.update(task, current=ticker)
            stock_id = stock_lookup.get((ticker, str(country)))
            if stock_id is None:
                progress.advance(task)
                continue

            try:
                _sync_prices(provider, stock_id, ticker, country, as_of)
                _sync_fundamentals(provider, stock_id, ticker, country)
                _sync_events(provider, stock_id, ticker, country)
                if country == Country.INDIA:
                    _sync_india_stock_data(provider, stock_id, ticker, country, as_of)
            except SymbolNotFoundError as exc:
                skipped.append(ticker)
                logger.warning(f"Data sync skipped for {ticker}: {exc}")
            except DataProviderError as exc:
                logger.warning(f"Data sync issue for {ticker}: {exc}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Unexpected data sync error for {ticker}: {exc}")

            progress.advance(task)

    logger.info(f"Market data sync complete — {len(tickers)} stocks, {len(skipped)} skipped")
    if skipped:
        logger.debug(f"Skipped tickers: {skipped}")

    # India-specific: update F&O ban and ASM/GSM flags on Stock rows
    india_tickers = [(t, c) for t, c in tickers if c == Country.INDIA]
    if india_tickers:
        logger.info("Syncing India market-structure flags (F&O ban / ASM-GSM)...")
        _sync_india_stock_flags(provider, india_tickers, stock_lookup)
        logger.info("Syncing India market breadth snapshot...")
        _sync_india_breadth(provider, as_of)

    _sync_general_news(provider, as_of, macro_context)


def _sync_prices(provider, stock_id: int, ticker: str, country, as_of: date) -> None:
    with get_session() as session:
        latest_date = session.execute(
            select(Price.date)
            .where(Price.stock_id == stock_id)
            .order_by(Price.date.desc())
            .limit(1)
        ).scalar_one_or_none()

    start = latest_date + timedelta(days=1) if latest_date else as_of - timedelta(days=PRICE_BACKFILL_DAYS)
    if start > as_of:
        return

    bars = provider.prices.get_daily_ohlcv(ticker, country, start, as_of)
    if not bars:
        return

    rows = [
        {
            "stock_id": stock_id,
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "adj_close": bar.adj_close,
            "volume": bar.volume,
        }
        for bar in bars
    ]

    stmt = sqlite_insert(Price).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "date"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
            "volume": stmt.excluded.volume,
        },
    )
    with get_session() as session:
        session.execute(stmt)


def _sync_fundamentals(provider, stock_id: int, ticker: str, country) -> None:
    snapshots = provider.fundamentals.get_quarterly_fundamentals(ticker, country, limit=20)
    if not snapshots:
        return

    rows = [
        {
            "stock_id": stock_id,
            "fiscal_date": snap.fiscal_date,
            "period": snap.period,
            "revenue": snap.revenue,
            "net_income": snap.net_income,
            "eps": snap.eps,
            "total_debt": snap.total_debt,
            "total_equity": snap.total_equity,
            "debt_equity": snap.debt_equity,
            "operating_cash_flow": snap.operating_cash_flow,
            "free_cash_flow": snap.free_cash_flow,
            "roe": snap.roe,
            "roce": snap.roce,
            "gross_margin": snap.gross_margin,
            "operating_margin": snap.operating_margin,
            "net_margin": snap.net_margin,
            "pe": snap.pe,
            "peg": snap.peg,
            "pb": snap.pb,
            "ev_ebitda": snap.ev_ebitda,
            "dividend_per_share": snap.dividend_per_share,
            "dividend_yield": snap.dividend_yield,
            "payout_ratio": snap.payout_ratio,
            "promoter_holding": snap.promoter_holding,
            # India-specific columns
            "promoter_pledge_pct": snap.promoter_pledge_pct,
            "fii_holding": snap.fii_holding,
            "dii_holding": snap.dii_holding,
            "is_consolidated": snap.is_consolidated,
            "data_source": snap.data_source,
            "gnpa_pct": snap.gnpa_pct,
            "nnpa_pct": snap.nnpa_pct,
            "nim_pct": snap.nim_pct,
            "casa_ratio": snap.casa_ratio,
            "credit_cost": snap.credit_cost,
            "capital_adequacy_ratio": snap.capital_adequacy_ratio,
        }
        for snap in snapshots
    ]

    stmt = sqlite_insert(Fundamental).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["stock_id", "fiscal_date"],
        set_={
            "period": stmt.excluded.period,
            "revenue": stmt.excluded.revenue,
            "net_income": stmt.excluded.net_income,
            "eps": stmt.excluded.eps,
            "total_debt": stmt.excluded.total_debt,
            "total_equity": stmt.excluded.total_equity,
            "debt_equity": stmt.excluded.debt_equity,
            "operating_cash_flow": stmt.excluded.operating_cash_flow,
            "free_cash_flow": stmt.excluded.free_cash_flow,
            "roe": stmt.excluded.roe,
            "roce": stmt.excluded.roce,
            "gross_margin": stmt.excluded.gross_margin,
            "operating_margin": stmt.excluded.operating_margin,
            "net_margin": stmt.excluded.net_margin,
            "pe": stmt.excluded.pe,
            "peg": stmt.excluded.peg,
            "pb": stmt.excluded.pb,
            "ev_ebitda": stmt.excluded.ev_ebitda,
            "dividend_per_share": stmt.excluded.dividend_per_share,
            "dividend_yield": stmt.excluded.dividend_yield,
            "payout_ratio": stmt.excluded.payout_ratio,
            "promoter_holding": stmt.excluded.promoter_holding,
            # India-specific columns
            "promoter_pledge_pct": stmt.excluded.promoter_pledge_pct,
            "fii_holding": stmt.excluded.fii_holding,
            "dii_holding": stmt.excluded.dii_holding,
            "is_consolidated": stmt.excluded.is_consolidated,
            "data_source": stmt.excluded.data_source,
            "gnpa_pct": stmt.excluded.gnpa_pct,
            "nnpa_pct": stmt.excluded.nnpa_pct,
            "nim_pct": stmt.excluded.nim_pct,
            "casa_ratio": stmt.excluded.casa_ratio,
            "credit_cost": stmt.excluded.credit_cost,
            "capital_adequacy_ratio": stmt.excluded.capital_adequacy_ratio,
        },
    )
    with get_session() as session:
        session.execute(stmt)


def _sync_events(provider, stock_id: int, ticker: str, country) -> None:
    events = provider.events.get_upcoming_events(ticker, country, within_days=EVENT_LOOKAHEAD_DAYS)
    if not events:
        return

    today = date.today()
    with get_session() as session:
        session.execute(
            delete(Event).where(
                Event.stock_id == stock_id,
                Event.event_date >= today,
                Event.event_type.in_(
                    [EventType.EARNINGS, EventType.EX_DIVIDEND, EventType.SPLIT]
                ),
            )
        )
        rows = [
            Event(
                stock_id=stock_id,
                event_type=event.event_type,
                event_date=event.event_date,
                meta=event.meta,
            )
            for event in events
        ]
        session.add_all(rows)


def _sync_general_news(provider, as_of: date, macro_context: MacroContext) -> None:
    since = datetime.combine(as_of - timedelta(days=GENERAL_NEWS_DAYS), time.min)
    articles = provider.news.get_general_news(since, limit=100)
    if not articles:
        return

    scorer = SentimentScorer()
    shock_detector = ShockDetector()
    now_cutoff = datetime.combine(as_of - timedelta(days=1), time.min)

    rows = []
    for article in articles:
        sentiment = scorer.score(article.headline)
        category = _categorize_headline(article.headline)
        rows.append(
            {
                "stream": NewsStream.GENERAL,
                "stock_id": None,
                "source": article.source,
                "headline": article.headline,
                "summary": article.summary,
                "url": article.url,
                "published_at": article.published_at.replace(tzinfo=None),
                "category": category,
                "sentiment_score": sentiment.compound,
                "sentiment_label": sentiment.label,
                "matched_keywords": None,
            }
        )

        if article.published_at >= now_cutoff:
            sig = shock_detector.evaluate(
                headline=article.headline,
                source=article.source,
                url=article.url,
                india_vix=macro_context.india_vix,
                india_vix_prev=macro_context.india_vix_prev,
                us_vix=macro_context.us_vix,
                us_vix_prev=macro_context.us_vix_prev,
            )
            if sig.banner and not _shock_exists(sig.headline, sig.source):
                shock_detector.persist(sig)

    stmt = sqlite_insert(NewsItem).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
    with get_session() as session:
        session.execute(stmt)


def _pull_macro_snapshot(provider, as_of: date) -> MacroContext:
    start = as_of - timedelta(days=MACRO_HISTORY_DAYS)

    # Phase 1: India market only — US macro indicators (US_VIX, SP_500, FEDFUNDS,
    # US_CPI_YOY, US_10Y) are not fetched. They will be re-enabled in Phase 2.
    india_vix_series = _safe_macro_series(provider, "INDIA_VIX", start, as_of)
    nifty_series = _safe_macro_series(provider, "NIFTY_50", start, as_of)
    usd_inr_series = _safe_macro_series(provider, "USD_INR", start, as_of)
    brent_series = _safe_macro_series(provider, "BRENT_OIL", start, as_of)
    india_repo_series = _safe_macro_series(provider, "INDIA_REPO_RATE", start, as_of)
    india_cpi_series = _safe_macro_series(provider, "INDIA_CPI_YOY", start, as_of)

    # US indicators — not fetched in Phase 1 (India-only mode)
    # us_vix_series = _safe_macro_series(provider, "US_VIX", start, as_of)
    # sp_series = _safe_macro_series(provider, "SP_500", start, as_of)
    # us_10y_series = _safe_macro_series(provider, "US_10Y", start, as_of)
    # fed_series = _safe_macro_series(provider, "FEDFUNDS", start, as_of)
    # us_cpi_series = _safe_macro_series(provider, "US_CPI_YOY", start, as_of)

    snapshot_values = {
        "date": as_of,
        "fed_funds_rate": None,          # Phase 2 (US market)
        "rbi_repo_rate": _latest_value(india_repo_series),
        "us_10y_yield": None,            # Phase 2 (US market)
        "india_10y_yield": None,
        "us_cpi_yoy": None,              # Phase 2 (US market)
        "india_cpi_yoy": _compute_yoy(india_cpi_series),
        "usd_inr": _latest_value(usd_inr_series),
        "india_vix": _latest_value(india_vix_series),
        "us_vix": None,                  # Phase 2 (US market)
        "brent_oil": _latest_value(brent_series),
        "gold": None,
        "nifty_50_close": _latest_value(nifty_series),
        "nifty_50_200dma": _rolling_average(nifty_series, 200),
        "sp_500_close": None,            # Phase 2 (US market)
        "sp_500_200dma": None,           # Phase 2 (US market)
    }

    stmt = sqlite_insert(MacroSnapshot).values(snapshot_values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["date"],
        set_={key: stmt.excluded[key] for key in snapshot_values if key != "date"},
    )
    with get_session() as session:
        session.execute(stmt)

    return MacroContext(
        india_vix=_latest_value(india_vix_series),
        india_vix_prev=_previous_value(india_vix_series),
        us_vix=None,    # Phase 2 (US market)
        us_vix_prev=None,  # Phase 2 (US market)
    )


def _persist_snapshot(
    *,
    diff_result: DiffResult,
    guardrail_results,
    run_date: date,
    run_started_at: datetime,
    picks_per_bucket: int,
    universe_size_raw: int,
    universe_size_filtered: int,
) -> None:
    with get_session() as session:
        existing = session.execute(
            select(RebalanceSnapshot).where(RebalanceSnapshot.run_date == run_date)
        ).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)
            session.flush()

        snapshot = RebalanceSnapshot(
            run_date=run_date,
            run_started_at=run_started_at,
            run_completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            macro_regime=MacroRegime(diff_result.macro_regime),
            shock_regime=diff_result.shock_regime,
            universe_size_raw=universe_size_raw,
            universe_size_filtered=universe_size_filtered,
            config_snapshot={
                "picks_per_bucket": picks_per_bucket,
            },
            errors=[],
        )
        session.add(snapshot)
        session.flush()

        stock_ids = {
            (row.ticker, str(row.country)): row.id
            for row in session.execute(select(Stock.id, Stock.ticker, Stock.country)).all()
        }

        ranked_by_key = {}
        for result in guardrail_results:
            for score_out in result.ranked + result.extended:
                ranked_by_key[(score_out.ticker, str(result.country), str(result.bucket))] = score_out

        for result in guardrail_results:
            for score_out in result.ranked + result.extended:
                stock_id = stock_ids.get((score_out.ticker, str(result.country)))
                if stock_id is None:
                    continue
                session.add(
                    Score(
                        snapshot_id=snapshot.id,
                        stock_id=stock_id,
                        bucket=result.bucket,
                        score=score_out.score,
                        qualified=score_out.qualified,
                        rank=score_out.rank,
                        factor_scores=score_out.factor_scores,
                        disqualifiers=score_out.disqualifiers,
                        snapshot_data=None,
                    )
                )


def _sync_india_stock_data(
    provider, stock_id: int, ticker: str, country, as_of: date
) -> None:
    """Sync bulk deals, insider trades, market depth, and derivatives for one India stock."""
    from pipeline.db.models import IndiaBulkDeal, IndiaInsiderTrade, IndiaMarketDepth, IndiaDerivatives

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Bulk deals (last 30 days)
    try:
        deals = provider.india.get_bulk_deals(ticker, country, limit=50)
        if deals:
            rows = [
                IndiaBulkDeal(
                    stock_id=stock_id,
                    deal_type=d.deal_type,
                    trade_date=d.trade_date,
                    client_name=d.client_name,
                    transaction_type=d.transaction_type,
                    quantity=d.quantity,
                    trade_price=d.trade_price,
                    source=d.source or "NSE",
                )
                for d in deals
            ]
            with get_session() as session:
                # Delete existing records for this stock in the last 90 days to avoid duplicates
                cutoff = as_of - timedelta(days=90)
                session.execute(
                    delete(IndiaBulkDeal).where(
                        IndiaBulkDeal.stock_id == stock_id,
                        IndiaBulkDeal.trade_date >= cutoff,
                    )
                )
                session.add_all(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Bulk deals unavailable for {ticker}: {exc}")

    # Insider trades (last 90 days)
    try:
        trades = provider.india.get_insider_trades(ticker, country, limit=50)
        if trades:
            rows = [
                IndiaInsiderTrade(
                    stock_id=stock_id,
                    person_name=t.person_name,
                    person_category=t.person_category,
                    transaction_type=t.transaction_type,
                    trade_date=t.trade_date,
                    from_date=t.from_date,
                    to_date=t.to_date,
                    shares_traded=t.shares_traded,
                    trade_price=t.trade_price,
                    post_trade_pct=t.post_trade_pct,
                    source=t.source or "NSE",
                )
                for t in trades
            ]
            with get_session() as session:
                cutoff = as_of - timedelta(days=180)
                session.execute(
                    delete(IndiaInsiderTrade).where(
                        IndiaInsiderTrade.stock_id == stock_id,
                        IndiaInsiderTrade.trade_date >= cutoff,
                    )
                )
                session.add_all(rows)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Insider trades unavailable for {ticker}: {exc}")

    # Market depth snapshot (live — only useful during market hours)
    try:
        depth = provider.india.get_market_depth(ticker, country)
        if depth is not None:
            buy_levels = [
                {"price": lvl.price, "qty": lvl.quantity, "orders": lvl.orders}
                for lvl in (depth.buy_depth or [])
            ]
            sell_levels = [
                {"price": lvl.price, "qty": lvl.quantity, "orders": lvl.orders}
                for lvl in (depth.sell_depth or [])
            ]
            row = IndiaMarketDepth(
                stock_id=stock_id,
                snapshot_at=now,
                buy_depth=buy_levels,
                sell_depth=sell_levels,
                total_buy_qty=depth.total_buy_qty,
                total_sell_qty=depth.total_sell_qty,
                source=depth.source or "NSE",
            )
            with get_session() as session:
                session.add(row)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Market depth unavailable for {ticker}: {exc}")

    # Derivatives / F&O sentiment
    try:
        deriv = provider.india.get_derivatives_sentiment(ticker, country)
        if deriv is not None:
            row_data = {
                "stock_id": stock_id,
                "as_of": as_of,
                "oi_futures": deriv.oi_futures,
                "oi_futures_change": deriv.oi_futures_change,
                "oi_call_total": deriv.oi_call_total,
                "oi_put_total": deriv.oi_put_total,
                "put_call_ratio": deriv.put_call_ratio,
                "max_pain_strike": deriv.max_pain_strike,
                "atm_iv": deriv.atm_iv,
                "top_call_oi_strike": deriv.top_call_oi_strike,
                "top_put_oi_strike": deriv.top_put_oi_strike,
                "source": deriv.source or "NSE",
            }
            stmt = sqlite_insert(IndiaDerivatives).values(row_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=["stock_id", "as_of"],
                set_={k: stmt.excluded[k] for k in row_data if k not in ("stock_id", "as_of")},
            )
            with get_session() as session:
                session.execute(stmt)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Derivatives sentiment unavailable for {ticker}: {exc}")


def _extract_symbols_from_nse_response(data, *key_candidates: str) -> set[str]:
    """Pull symbol strings from a variety of NSE payload shapes."""
    if isinstance(data, dict):
        records = data.get("data") or data.get("secBanList") or []
    elif isinstance(data, list):
        records = data
    else:
        return set()
    symbols: set[str] = set()
    for rec in records:
        sym = next(
            (rec.get(k) for k in key_candidates if rec.get(k)),
            None,
        )
        if sym:
            symbols.add(sym.upper())
    return symbols


def _sync_india_stock_flags(
    provider,
    india_tickers: list[tuple[str, Country]],
    stock_lookup: dict[tuple[str, str], int],
) -> None:
    """Update in_fno_ban and in_asm_gsm flags on Stock rows from live NSE data."""
    india_market = getattr(provider.india, "_india", None)
    if india_market is None:
        logger.debug("IndiaMarketProvider not accessible — skipping flag sync")
        return

    nse_client = getattr(india_market, "_nse", None)
    if nse_client is None:
        logger.debug("NSE client not accessible — skipping flag sync")
        return

    fno_banned: set[str] = set()
    asm_gsm: set[str] = set()

    try:
        fno_banned = _extract_symbols_from_nse_response(
            nse_client.get_fno_ban_list(), "symbol", "Symbol", "scrip"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"F&O ban list fetch failed: {exc}")

    try:
        asm_gsm = _extract_symbols_from_nse_response(
            nse_client.get_asm_list(), "symbol", "Symbol"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ASM/GSM list fetch failed: {exc}")

    if not fno_banned and not asm_gsm:
        return

    with get_session() as session:
        for ticker, _ in india_tickers:
            stock_id = stock_lookup.get((ticker, str(Country.INDIA)))
            if stock_id is None:
                continue
            session.execute(
                Stock.__table__.update()
                .where(Stock.id == stock_id)
                .values(
                    in_fno_ban=ticker.upper() in fno_banned,
                    in_asm_gsm=ticker.upper() in asm_gsm,
                )
            )


def _sync_india_breadth(provider, as_of: date) -> None:
    """Persist one IndiaMarketBreadth row for today from NSE breadth data."""
    try:
        breadth = provider.india.get_market_breadth()
        if breadth is None:
            return

        row_data = {
            "as_of": as_of,
            "advances": breadth.advances,
            "declines": breadth.declines,
            "unchanged": breadth.unchanged,
            "advance_decline_ratio": breadth.advance_decline_ratio,
            "india_vix": breadth.india_vix,
            "india_vix_change_pct": breadth.india_vix_change_pct,
            "nifty_50": breadth.nifty_50,
            "nifty_50_change_pct": breadth.nifty_50_change_pct,
            "sensex": breadth.sensex,
            "sensex_change_pct": breadth.sensex_change_pct,
            "nifty_bank": breadth.nifty_bank,
            "nifty_it": breadth.nifty_it,
            "nifty_fmcg": breadth.nifty_fmcg,
            "nifty_auto": breadth.nifty_auto,
            "nifty_pharma": breadth.nifty_pharma,
            "nifty_realty": breadth.nifty_realty,
            "nifty_metal": breadth.nifty_metal,
            "nifty_energy": breadth.nifty_energy,
            "source": "NSE",
        }
        stmt = sqlite_insert(IndiaMarketBreadth).values(row_data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["as_of"],
            set_={k: stmt.excluded[k] for k in row_data if k != "as_of"},
        )
        with get_session() as session:
            session.execute(stmt)
        logger.debug(f"India market breadth synced for {as_of}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"India breadth sync failed: {exc}")


def _stock_lookup() -> dict[tuple[str, str], int]:
    with get_session() as session:
        rows = session.execute(select(Stock.id, Stock.ticker, Stock.country)).all()
    return {(row.ticker, str(row.country)): row.id for row in rows}


def _safe_macro_series(provider, indicator: str, start: date, end: date):
    try:
        return provider.macro.get_series(indicator, start, end)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Macro series unavailable for {indicator}: {exc}")
        return []


def _macro_regime_for_date(run_date: date) -> MacroRegime:
    with get_session() as session:
        row = session.execute(
            select(MacroSnapshot).where(MacroSnapshot.date == run_date)
        ).scalar_one_or_none()
    if row is None:
        return MacroRegime.CAUTION
    return compute_macro_regime(
        row.nifty_50_close,
        row.nifty_50_200dma,
        row.sp_500_close,
        row.sp_500_200dma,
    )


def _latest_value(series) -> float | None:
    if not series:
        return None
    return float(series[-1].value)


def _previous_value(series) -> float | None:
    if len(series) < 2:
        return None
    return float(series[-2].value)


def _rolling_average(series, window: int) -> float | None:
    if len(series) < window:
        return None
    values = [reading.value for reading in series[-window:]]
    return float(sum(values) / len(values))


def _compute_yoy(series) -> float | None:
    if len(series) < 13:
        return _latest_value(series)
    latest = series[-1].value
    year_ago = series[-13].value
    if year_ago == 0:
        return None
    return ((latest / year_ago) - 1.0) * 100.0


def _categorize_headline(headline: str) -> NewsCategory:
    lower = headline.lower()
    if any(word in lower for word in ("earnings", "results", "guidance", "eps", "quarter")):
        return NewsCategory.EARNINGS
    if any(word in lower for word in ("ceo", "cfo", "board", "management", "leadership")):
        return NewsCategory.MANAGEMENT
    if any(word in lower for word in ("regulator", "sec", "rbi", "fda", "investigation", "lawsuit", "antitrust")):
        return NewsCategory.REGULATORY
    if any(word in lower for word in ("acquisition", "acquire", "merger", "buyout", "stake sale")):
        return NewsCategory.M_AND_A
    if any(word in lower for word in ("dividend", "buyback", "split", "ex-dividend")):
        return NewsCategory.DIVIDEND
    return NewsCategory.OTHER


def _shock_exists(headline: str, source: str) -> bool:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    with get_session() as session:
        row = session.execute(
            select(ShockEvent.id)
            .where(
                ShockEvent.headline == headline,
                ShockEvent.source == source,
                ShockEvent.triggered_at >= cutoff,
            )
            .limit(1)
        ).scalar_one_or_none()
    return row is not None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the monthly rebalance pipeline.")
    parser.add_argument("--fresh-capital", type=float, default=0.0, help="Fresh capital to deploy")
    parser.add_argument("--picks", type=int, default=10, help="Stocks per bucket (default 10)")
    parser.add_argument("--date", type=str, default=None, help="Override run date YYYY-MM-DD")
    args = parser.parse_args()

    run_date_arg = date.fromisoformat(args.date) if args.date else None
    run_pipeline(
        as_of=run_date_arg,
        fresh_capital=args.fresh_capital,
        picks_per_bucket=args.picks,
    )

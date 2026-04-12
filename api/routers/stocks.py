"""GET /api/stocks/{ticker} — stock detail card."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.stocks import (
    AnalystForecast,
    EventItem,
    FundamentalData,
    HoldingDetail,
    NewsItem,
    PeerStock,
    PricePoint,
    QuarterlyEstimate,
    ScoreBucket,
    SentimentSummary,
    StockDetailResponse,
)
from pipeline.db.enums import Bucket, Country
from pipeline.db.models import (
    Event,
    Fundamental,
    Holding,
    NewsItem as NewsItemModel,
    Price,
    RebalanceSnapshot,
    Score,
    Stock,
)
from pipeline.portfolio.diff import _format_reason
from pipeline.providers.errors import MissingApiKeyError, PlanLimitError, SymbolNotFoundError
from pipeline.providers.fmp_provider import FMPProvider
from pipeline.scoring.base import ScoreOutput

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{ticker}", response_model=StockDetailResponse)
def get_stock_detail(ticker: str, db: Session = Depends(get_db)) -> StockDetailResponse:
    """Full detail card for a single stock — all 7 tabs worth of data."""

    stock = db.execute(
        select(Stock).where(Stock.ticker == ticker.upper())
    ).scalar_one_or_none()
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")

    # Latest fundamental
    fund_row = db.execute(
        select(Fundamental)
        .where(Fundamental.stock_id == stock.id)
        .order_by(Fundamental.fiscal_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    # Latest price
    latest_price_row = db.execute(
        select(Price)
        .where(Price.stock_id == stock.id)
        .order_by(Price.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    current_price = latest_price_row.close if latest_price_row else None

    # Price history — last 12 months
    since = date.today() - timedelta(days=365)
    price_rows = db.execute(
        select(Price)
        .where(Price.stock_id == stock.id, Price.date >= since)
        .order_by(Price.date)
    ).scalars().all()

    # News (last 30 items)
    news_rows = db.execute(
        select(NewsItemModel)
        .where(NewsItemModel.stock_id == stock.id)
        .order_by(NewsItemModel.published_at.desc())
        .limit(30)
    ).scalars().all()

    # Events
    event_rows = db.execute(
        select(Event)
        .where(Event.stock_id == stock.id)
        .order_by(Event.event_date)
        .limit(10)
    ).scalars().all()

    # Holding detail
    holding_row = db.execute(
        select(Holding).where(Holding.stock_id == stock.id)
    ).scalar_one_or_none()
    holding_detail = _build_holding_detail(holding_row, current_price, db) if holding_row else None

    # Scores from latest snapshot (all buckets)
    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    score_rows = []
    if snapshot:
        score_rows = db.execute(
            select(Score)
            .where(Score.snapshot_id == snapshot.id, Score.stock_id == stock.id)
        ).scalars().all()

    scores = [
        ScoreBucket(
            bucket=Bucket(s.bucket),
            score=s.score,
            qualified=s.qualified,
            rank=s.rank,
            factor_scores=s.factor_scores or {},
            reason=_format_reason(ScoreOutput(
                ticker=stock.ticker,
                bucket=Bucket(s.bucket),
                score=s.score,
                qualified=s.qualified,
                factor_scores=s.factor_scores or {},
                rank=s.rank,
            )),
        )
        for s in score_rows
    ]

    # Plain-English reason (F-7.9) — from highest-scoring bucket
    best_score = max(score_rows, key=lambda s: s.score) if score_rows else None
    plain_reason = _format_reason(ScoreOutput(
        ticker=stock.ticker,
        bucket=Bucket(best_score.bucket) if best_score else Bucket.QUALITY_MOMENTUM,
        score=best_score.score if best_score else 0.0,
        qualified=best_score.qualified if best_score else False,
        factor_scores=best_score.factor_scores if best_score else {},
    )) if best_score else f"No score data for {ticker}."

    provider = FMPProvider()
    live_news = _load_live_news(provider, stock)
    news_items = _merge_news(news_rows, live_news)
    sentiment = _compute_sentiment(news_rows)
    live_events = _load_live_events(provider, stock)
    events = _merge_events(event_rows, live_events)
    forecasts = _load_forecasts(provider, stock, current_price)
    peers, peers_note = _build_peers(provider, stock, snapshot.id if snapshot else None, db)

    return StockDetailResponse(
        ticker=stock.ticker,
        country=Country(stock.country),
        company_name=stock.name,
        sector=stock.sector,
        description=stock.description,
        market_cap=stock.market_cap,
        current_price=current_price,
        fundamentals=FundamentalData(
            revenue=fund_row.revenue,
            net_income=fund_row.net_income,
            eps=fund_row.eps,
            roe=fund_row.roe,
            roce=fund_row.roce,
            debt_equity=fund_row.debt_equity,
            free_cash_flow=fund_row.free_cash_flow,
            pe_ratio=fund_row.pe,
            pb_ratio=fund_row.pb,
            peg_ratio=fund_row.peg,
            dividend_yield=fund_row.dividend_yield,
            payout_ratio=fund_row.payout_ratio,
            as_of=fund_row.fiscal_date,
        ) if fund_row else None,
        sentiment=sentiment,
        forecasts=forecasts,
        peers=peers,
        peers_note=peers_note,
        holding=holding_detail,
        events=[
            EventItem(
                event_type=e.event_type,
                event_date=e.event_date,
                description=str(e.meta) if e.meta else None,
            )
            for e in events
        ],
        news=news_items,
        scores=scores,
        plain_english_reason=plain_reason,
        price_history=[
            PricePoint(date=p.date, close=p.close, volume=float(p.volume))
            for p in price_rows
        ],
    )


def _compute_sentiment(news_rows: list) -> SentimentSummary | None:
    if not news_rows:
        return None
    from pipeline.db.enums import SentimentLabel
    pos = sum(1 for n in news_rows if n.sentiment_label == SentimentLabel.POSITIVE)
    neg = sum(1 for n in news_rows if n.sentiment_label == SentimentLabel.NEGATIVE)
    neu = sum(1 for n in news_rows if n.sentiment_label == SentimentLabel.NEUTRAL)
    scores = [n.sentiment_score for n in news_rows if n.sentiment_score is not None]
    avg = sum(scores) / len(scores) if scores else None
    return SentimentSummary(
        positive_count=pos,
        neutral_count=neu,
        negative_count=neg,
        avg_compound=avg,
        headline_volume_30d=len(news_rows),
    )


def _build_holding_detail(
    holding: Holding,
    current_price: float | None,
    db: Session,
) -> HoldingDetail:
    cost_basis = holding.quantity * holding.avg_buy_price
    current_value = holding.quantity * current_price if current_price else None
    pnl = current_value - cost_basis if current_value is not None else None
    pnl_pct = pnl / cost_basis * 100 if (pnl is not None and cost_basis > 0) else None
    days = (date.today() - holding.buy_date).days if holding.buy_date else None

    # Total portfolio value for % calculation
    all_holdings = db.execute(select(Holding)).scalars().all()
    portfolio_total = sum(
        h.quantity * (current_price or h.avg_buy_price) for h in all_holdings
    )
    pct = current_value / portfolio_total * 100 if (current_value and portfolio_total > 0) else None

    # LTCG warning: India only, approaching 12 months
    ltcg_warn = (
        holding.stock.country == "IN"
        and days is not None
        and 330 <= days <= 365   # warn in the 11th month
    )

    return HoldingDetail(
        qty=holding.quantity,
        avg_buy_price=holding.avg_buy_price,
        buy_date=holding.buy_date,
        current_price=current_price,
        current_value=current_value,
        unrealized_pnl=pnl,
        unrealized_pnl_pct=pnl_pct,
        days_held=days,
        ltcg_warning=ltcg_warn,
        pct_of_portfolio=pct,
    )


def _load_forecasts(
    provider: FMPProvider,
    stock: Stock,
    current_price: float | None,
) -> AnalystForecast | None:
    country = Country(stock.country)
    try:
        forecast = provider.get_analyst_forecast(
            stock.ticker,
            country,
            current_price=current_price,
        )
    except MissingApiKeyError:
        return AnalystForecast(
            analyst_count=None,
            buy_count=None,
            hold_count=None,
            sell_count=None,
            target_high=None,
            target_low=None,
            target_avg=None,
            current_price=current_price,
            availability="missing_key",
            note="Set FMP_API_KEY to load analyst targets and EPS estimates.",
            quarterly_estimates=[],
        )
    except PlanLimitError:
        return AnalystForecast(
            analyst_count=None,
            buy_count=None,
            hold_count=None,
            sell_count=None,
            target_high=None,
            target_low=None,
            target_avg=None,
            current_price=current_price,
            availability="plan_limited",
            note="Your current FMP plan does not expose analyst forecast endpoints for this stock.",
            quarterly_estimates=[],
        )
    except SymbolNotFoundError:
        return AnalystForecast(
            analyst_count=None,
            buy_count=None,
            hold_count=None,
            sell_count=None,
            target_high=None,
            target_low=None,
            target_avg=None,
            current_price=current_price,
            availability="unavailable",
            note=f"No analyst forecast data was returned for {stock.ticker}.",
            quarterly_estimates=[],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Forecast load failed for {stock.ticker}: {exc}")
        return AnalystForecast(
            analyst_count=None,
            buy_count=None,
            hold_count=None,
            sell_count=None,
            target_high=None,
            target_low=None,
            target_avg=None,
            current_price=current_price,
            availability="error",
            note="Analyst forecast data could not be loaded right now.",
            quarterly_estimates=[],
        )

    if forecast is None:
        return AnalystForecast(
            analyst_count=None,
            buy_count=None,
            hold_count=None,
            sell_count=None,
            target_high=None,
            target_low=None,
            target_avg=None,
            current_price=current_price,
            availability="empty",
            note="No analyst forecast data is available for this stock yet.",
            quarterly_estimates=[],
        )

    return AnalystForecast(
        analyst_count=forecast.analyst_count,
        buy_count=forecast.buy_count,
        hold_count=forecast.hold_count,
        sell_count=forecast.sell_count,
        target_high=forecast.target_high,
        target_low=forecast.target_low,
        target_avg=forecast.target_avg,
        current_price=forecast.current_price or current_price,
        consensus_rating=forecast.consensus_rating,
        availability="live",
        note=None,
        quarterly_estimates=[
            QuarterlyEstimate(
                period=estimate.period,
                fiscal_date=estimate.fiscal_date,
                eps_estimate=estimate.eps_estimate,
                revenue_estimate=estimate.revenue_estimate,
                analyst_count=estimate.analyst_count,
            )
            for estimate in forecast.quarterly_estimates
        ],
    )


def _build_peers(
    provider: FMPProvider,
    stock: Stock,
    snapshot_id: int | None,
    db: Session,
) -> tuple[list[PeerStock], str | None]:
    notes: list[str] = []
    peer_tickers: list[str] = []

    try:
        peer_tickers = provider.get_stock_peers(stock.ticker, Country(stock.country))
    except MissingApiKeyError:
        notes.append("Set FMP_API_KEY to load provider-backed peers.")
    except PlanLimitError:
        notes.append("Using local same-sector peers because the current FMP plan does not expose peer lookup.")
    except SymbolNotFoundError:
        notes.append(f"No provider-backed peers were returned for {stock.ticker}; using local same-sector peers.")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Peer load failed for {stock.ticker}: {exc}")
        notes.append("Using local same-sector peers because provider lookup failed.")

    if peer_tickers:
        local_rows = db.execute(
            select(Stock)
            .options(selectinload(Stock.fundamentals))
            .where(Stock.ticker.in_(peer_tickers))
        ).scalars().all()
        local_by_ticker = {row.ticker: row for row in local_rows}

        peers: list[PeerStock] = []
        for ticker in peer_tickers:
            peer = local_by_ticker.get(ticker)
            if peer is not None:
                peers.append(_peer_to_schema(peer, snapshot_id, db))
                continue

            remote_peer = _build_remote_peer(provider, ticker, Country(stock.country))
            if remote_peer is not None:
                peers.append(remote_peer)

        if peers:
            return peers[:8], " ".join(notes) if notes else None

    if not stock.sector:
        return [], " ".join(notes) if notes else None

    peer_rows = db.execute(
        select(Stock)
        .options(selectinload(Stock.fundamentals))
        .where(
            Stock.sector == stock.sector,
            Stock.id != stock.id,
        )
        .limit(8)
    ).scalars().all()

    peers = [_peer_to_schema(peer, snapshot_id, db) for peer in peer_rows]
    if peers and not notes:
        notes.append("Showing same-sector peers from the local research universe.")
    return peers, " ".join(notes) if notes else None


def _peer_to_schema(peer: Stock, snapshot_id: int | None, db: Session) -> PeerStock:
    latest_fund = max(peer.fundamentals, key=lambda f: f.fiscal_date) if peer.fundamentals else None
    membership: list[Bucket] = []
    if snapshot_id is not None:
        membership = [
            Bucket(bucket)
            for bucket, in db.execute(
                select(Score.bucket).where(
                    Score.snapshot_id == snapshot_id,
                    Score.stock_id == peer.id,
                    Score.qualified.is_(True),
                )
            ).all()
        ]

    return PeerStock(
        ticker=peer.ticker,
        company_name=peer.name,
        pe_ratio=latest_fund.pe if latest_fund else None,
        roe=latest_fund.roe if latest_fund else None,
        growth_rate=_growth_rate_from_fundamentals(peer.fundamentals),
        market_cap=peer.market_cap,
        bucket_membership=membership,
    )


def _build_remote_peer(
    provider: FMPProvider,
    ticker: str,
    country: Country,
) -> PeerStock | None:
    try:
        profile = provider.get_profile(ticker, country)
        fundamentals = provider.get_quarterly_fundamentals(ticker, country, limit=8)
    except (MissingApiKeyError, PlanLimitError, SymbolNotFoundError):
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Remote peer enrichment failed for {ticker}: {exc}")
        return None

    latest = fundamentals[0] if fundamentals else None
    return PeerStock(
        ticker=ticker,
        company_name=profile.name,
        pe_ratio=latest.pe if latest else None,
        roe=latest.roe if latest else None,
        growth_rate=_growth_rate_from_snapshots(fundamentals),
        market_cap=profile.market_cap,
        bucket_membership=[],
    )


def _growth_rate_from_fundamentals(fundamentals: list) -> float | None:
    if not fundamentals:
        return None
    rows = sorted(fundamentals, key=lambda row: row.fiscal_date, reverse=True)
    if len(rows) >= 5 and rows[4].revenue not in (None, 0):
        latest = rows[0].revenue
        prior = rows[4].revenue
        if latest is not None and prior not in (None, 0):
            return ((latest - prior) / abs(prior)) * 100.0
    return None


def _growth_rate_from_snapshots(fundamentals) -> float | None:
    if len(fundamentals) < 5:
        return None
    latest = fundamentals[0].revenue
    prior = fundamentals[4].revenue
    if latest is None or prior in (None, 0):
        return None
    return ((latest - prior) / abs(prior)) * 100.0


def _load_live_events(provider: FMPProvider, stock: Stock) -> list:
    try:
        return provider.get_upcoming_events(stock.ticker, Country(stock.country), within_days=120)
    except (MissingApiKeyError, PlanLimitError, SymbolNotFoundError):
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Live event load failed for {stock.ticker}: {exc}")
        return []


def _load_live_news(provider: FMPProvider, stock: Stock):
    try:
        return provider.get_stock_news(
            stock.ticker,
            Country(stock.country),
            since=datetime.utcnow() - timedelta(days=30),
            limit=20,
        )
    except (MissingApiKeyError, PlanLimitError, SymbolNotFoundError):
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Live news load failed for {stock.ticker}: {exc}")
        return []


def _merge_news(news_rows: list[NewsItemModel], live_news) -> list[NewsItem]:
    items = [
        NewsItem(
            id=row.id,
            headline=row.headline,
            source=row.source,
            url=row.url,
            published_at=row.published_at,
            sentiment=row.sentiment_label,
            compound_score=row.sentiment_score,
            category=row.category,
        )
        for row in news_rows
    ]
    if not live_news:
        return items

    existing_urls = {item.url for item in items if item.url}
    for idx, article in enumerate(live_news, start=1):
        if article.url in existing_urls:
            continue
        items.append(
            NewsItem(
                id=-idx,
                headline=article.headline,
                source=article.source,
                url=article.url,
                published_at=article.published_at,
                sentiment=None,
                compound_score=None,
                category=None,
            )
        )
    items.sort(key=lambda item: item.published_at or datetime.min, reverse=True)
    return items[:30]


def _merge_events(event_rows: list[Event], live_events: list) -> list:
    if not live_events:
        return event_rows

    existing = {
        (str(event.event_type), event.event_date)
        for event in event_rows
    }
    merged = list(event_rows)
    for event in live_events:
        key = (str(event.event_type), event.event_date)
        if key in existing:
            continue
        merged.append(
            type(
                "LiveEventRow",
                (),
                {
                    "event_type": event.event_type,
                    "event_date": event.event_date,
                    "meta": event.meta,
                },
            )()
        )
        existing.add(key)
    merged.sort(key=lambda event: event.event_date or date.max)
    return merged[:10]

"""GET /api/stocks/{ticker} — 7-tab stock detail card."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.stocks import (
    EventItem,
    FundamentalData,
    HoldingDetail,
    NewsItem,
    PricePoint,
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

    # Sentiment summary
    sentiment = _compute_sentiment(news_rows)

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

    return StockDetailResponse(
        ticker=stock.ticker,
        country=Country(stock.country),
        company_name=stock.name,
        sector=stock.sector,
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
        forecasts=None,     # analyst forecasts — FMP endpoint, to be wired in v1.1
        peers=[],           # peers — FMP peers endpoint, to be wired in v1.1
        holding=holding_detail,
        events=[
            EventItem(
                event_type=e.event_type,
                event_date=e.event_date,
                description=str(e.meta) if e.meta else None,
            )
            for e in event_rows
        ],
        news=[
            NewsItem(
                id=n.id,
                headline=n.headline,
                source=n.source,
                url=n.url,
                published_at=n.published_at,
                sentiment=n.sentiment_label,
                compound_score=n.sentiment_score,
                category=n.category,
            )
            for n in news_rows
        ],
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

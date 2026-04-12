"""Portfolio router — holdings CRUD + summary with LTCG flags.

GET    /api/portfolio                  — all holdings + summary
POST   /api/portfolio/holdings         — add a holding
PUT    /api/portfolio/holdings/{id}    — update qty / avg price / buy date
DELETE /api/portfolio/holdings/{id}    — remove a holding
GET    /api/portfolio/summary          — totals, sector allocation, benchmarks
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.schemas.portfolio import (
    AddHoldingRequest,
    BenchmarkReturn,
    HoldingRow,
    PortfolioResponse,
    PortfolioSummary,
    SectorAllocation,
    UpdateHoldingRequest,
)
from pipeline.db.enums import Broker, Country
from pipeline.db.models import Holding, Price, Stock

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db)) -> PortfolioResponse:
    holdings = db.execute(
        select(Holding).options(selectinload(Holding.stock))
    ).scalars().all()

    price_map = _latest_prices(holdings, db)
    rows = [_build_row(h, price_map) for h in holdings]
    summary = _build_summary(rows)

    return PortfolioResponse(holdings=rows, summary=summary)


@router.post("/holdings", status_code=201, response_model=HoldingRow)
def add_holding(body: AddHoldingRequest, db: Session = Depends(get_db)) -> HoldingRow:
    stock = db.execute(
        select(Stock).where(
            Stock.ticker == body.ticker.upper(),
            Stock.country == body.country,
        )
    ).scalar_one_or_none()

    if stock is None:
        # Auto-create a minimal stock row so the holding can be saved
        stock = Stock(
            ticker=body.ticker.upper(),
            country=body.country,
            name=body.ticker.upper(),
            currency="INR" if body.country == Country.INDIA else "USD",
        )
        db.add(stock)
        db.flush()

    holding = Holding(
        stock_id=stock.id,
        quantity=body.qty,
        avg_buy_price=body.avg_buy_price,
        buy_date=body.buy_date or date.today(),
        broker=Broker.KITE if body.country == Country.INDIA else Broker.VESTED,
    )
    db.add(holding)
    db.commit()
    db.refresh(holding)

    price_map = _latest_prices([holding], db)
    return _build_row(holding, price_map)


@router.put("/holdings/{holding_id}", response_model=HoldingRow)
def update_holding(
    holding_id: int,
    body: UpdateHoldingRequest,
    db: Session = Depends(get_db),
) -> HoldingRow:
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")

    if body.qty is not None:
        holding.quantity = body.qty
    if body.avg_buy_price is not None:
        holding.avg_buy_price = body.avg_buy_price
    if body.buy_date is not None:
        holding.buy_date = body.buy_date

    db.commit()
    db.refresh(holding)
    price_map = _latest_prices([holding], db)
    return _build_row(holding, price_map)


@router.delete("/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: int, db: Session = Depends(get_db)) -> None:
    holding = db.get(Holding, holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail="Holding not found")
    db.delete(holding)
    db.commit()


@router.get("/summary", response_model=PortfolioSummary)
def get_summary(db: Session = Depends(get_db)) -> PortfolioSummary:
    holdings = db.execute(
        select(Holding).options(selectinload(Holding.stock))
    ).scalars().all()
    price_map = _latest_prices(holdings, db)
    rows = [_build_row(h, price_map) for h in holdings]
    return _build_summary(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _latest_prices(holdings: list[Holding], db: Session) -> dict[int, float]:
    """Return {stock_id: latest_close} for each holding."""
    price_map: dict[int, float] = {}
    for h in holdings:
        row = db.execute(
            select(Price.close)
            .where(Price.stock_id == h.stock_id)
            .order_by(Price.date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is not None:
            price_map[h.stock_id] = row
    return price_map


def _build_row(holding: Holding, price_map: dict[int, float]) -> HoldingRow:
    current_price = price_map.get(holding.stock_id)
    cost_basis = holding.quantity * holding.avg_buy_price
    current_value = holding.quantity * current_price if current_price else None
    pnl = current_value - cost_basis if current_value is not None else None
    pnl_pct = pnl / cost_basis * 100 if (pnl is not None and cost_basis > 0) else None
    days = (date.today() - holding.buy_date).days if holding.buy_date else None
    ltcg = (
        holding.stock.country == Country.INDIA
        and days is not None
        and 330 <= days <= 365
    )
    return HoldingRow(
        id=holding.id,
        ticker=holding.stock.ticker,
        name=holding.stock.name,
        sector=holding.stock.sector,
        country=Country(holding.stock.country),
        qty=holding.quantity,
        avg_buy_price=holding.avg_buy_price,
        buy_date=holding.buy_date,
        current_price=current_price,
        current_value=current_value,
        cost_basis=cost_basis,
        unrealized_pnl=pnl,
        unrealized_pnl_pct=pnl_pct,
        days_held=days,
        ltcg_warning=ltcg,
        pct_of_portfolio=None,   # filled in summary
    )


def _build_summary(rows: list[HoldingRow]) -> PortfolioSummary:
    total_value = sum(r.current_value or r.cost_basis for r in rows)
    total_cost = sum(r.cost_basis for r in rows)
    total_pnl = total_value - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost > 0 else 0.0

    # Fill pct_of_portfolio on each row
    for r in rows:
        val = r.current_value or r.cost_basis
        r.pct_of_portfolio = val / total_value * 100 if total_value > 0 else 0.0

    india_value = sum(
        (r.current_value or r.cost_basis) for r in rows if r.country == Country.INDIA
    )
    us_value = total_value - india_value

    sector_totals: dict[str, float] = {}
    for r in rows:
        sector = r.sector or "Unclassified"
        row_value = r.current_value or r.cost_basis
        sector_totals[sector] = sector_totals.get(sector, 0.0) + row_value

    sector_allocation = [
        SectorAllocation(
            sector=sector,
            value=value,
            pct=value / total_value * 100 if total_value > 0 else 0.0,
            over_concentrated=(value / total_value * 100) > 25 if total_value > 0 else False,
        )
        for sector, value in sorted(sector_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    return PortfolioSummary(
        total_value=total_value,
        total_cost=total_cost,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        india_value=india_value,
        us_value=us_value,
        india_pct=india_value / total_value * 100 if total_value > 0 else 0.0,
        us_pct=us_value / total_value * 100 if total_value > 0 else 0.0,
        sector_allocation=sector_allocation,
        benchmarks=[
            BenchmarkReturn(name="Nifty 50", return_pct=None),
            BenchmarkReturn(name="S&P 500", return_pct=None),
        ],
    )

"""Kite Connect (Zerodha) OAuth integration.

GET  /api/kite/status    — check connection status
GET  /api/kite/login     — returns Zerodha login URL
GET  /api/kite/callback  — OAuth callback (browser redirect from Zerodha)
POST /api/kite/sync      — pull holdings from Kite and upsert into portfolio DB
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from pipeline.config import settings
from pipeline.db.enums import Broker, Country
from pipeline.db.models import Holding, SettingKV, Stock

router = APIRouter(prefix="/api/kite", tags=["kite"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kite_api_key() -> str:
    return settings.kite_api_key.strip()


def _kite_api_secret() -> str:
    return settings.kite_api_secret.strip()


def _frontend_url() -> str:
    return settings.frontend_url.rstrip("/")


def _get_kite():
    """Return a configured KiteConnect instance. Raises HTTP 500 if setup is incomplete."""
    try:
        from kiteconnect import KiteConnect  # type: ignore[import]
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="kiteconnect not installed. Run: pip install kiteconnect",
        ) from exc
    api_key = _kite_api_key()
    if not api_key:
        raise HTTPException(status_code=500, detail="KITE_API_KEY not set in .env")
    return KiteConnect(api_key=api_key)


def _load_token(db: Session) -> str | None:
    row = db.execute(
        select(SettingKV).where(SettingKV.key == "kite_access_token")
    ).scalar_one_or_none()
    return str(row.value) if row else None


def _save_kv(db: Session, updates: dict[str, str]) -> None:
    for key, value in updates.items():
        row = db.execute(select(SettingKV).where(SettingKV.key == key)).scalar_one_or_none()
        if row is None:
            db.add(SettingKV(key=key, value=value))
        else:
            row.value = value
    db.commit()


def _sync_holdings(db: Session, kite) -> dict[str, int]:
    try:
        raw_holdings = kite.holdings()
    except Exception as exc:
        logger.error(f"Kite holdings fetch failed: {exc}")
        raise HTTPException(status_code=502, detail=f"Kite API error: {exc}") from exc

    logger.info(f"Kite returned {len(raw_holdings)} holding rows")

    upserted = 0
    skipped = 0

    for holding_row in raw_holdings:
        ticker: str = str(holding_row["tradingsymbol"]).upper()
        qty: float = float(holding_row.get("quantity", 0))
        avg_price: float = float(holding_row.get("average_price", 0))

        if qty <= 0:
            skipped += 1
            continue

        stock = db.execute(
            select(Stock).where(Stock.ticker == ticker, Stock.country == Country.INDIA)
        ).scalar_one_or_none()

        if stock is None:
            stock = Stock(
                ticker=ticker,
                country=Country.INDIA,
                name=ticker,
                currency="INR",
            )
            db.add(stock)
            db.flush()

        holding = db.execute(
            select(Holding).where(
                Holding.stock_id == stock.id,
                Holding.broker == Broker.KITE,
            )
        ).scalar_one_or_none()

        if holding is None:
            holding = Holding(
                stock_id=stock.id,
                quantity=qty,
                avg_buy_price=avg_price,
                buy_date=date.today(),   # Kite doesn't expose buy date
                broker=Broker.KITE,
            )
            db.add(holding)
        else:
            holding.quantity = qty
            holding.avg_buy_price = avg_price

        upserted += 1

    db.commit()
    logger.info(f"Kite sync complete → upserted={upserted} skipped={skipped}")
    return {"upserted": upserted, "skipped": skipped, "total": len(raw_holdings)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def kite_status(db: Session = Depends(get_db)) -> dict:
    """Return whether Kite is connected and whether today's token is valid."""
    token = _load_token(db)
    token_date_row = db.execute(
        select(SettingKV).where(SettingKV.key == "kite_token_date")
    ).scalar_one_or_none()
    token_date = str(token_date_row.value) if token_date_row else None

    connected = token is not None
    stale = token_date != str(date.today()) if token_date else True
    logger.info(f"GET /api/kite/status connected={connected} token_date={token_date} stale={stale}")
    return {
        "connected": connected,
        "token_date": token_date,
        "stale": stale,
        "api_key_set": bool(_kite_api_key()),
    }


@router.get("/login")
def kite_login() -> dict:
    """Return the Zerodha login URL. Frontend opens this in a new tab."""
    kite = _get_kite()
    url = kite.login_url()
    logger.info(f"GET /api/kite/login → {url}")
    return {"login_url": url}


@router.get("/callback")
def kite_callback(
    request_token: str | None = None,
    action: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Zerodha redirects here after login with ?request_token=XX&status=success.
    Exchanges request_token for an access_token and stores it, then redirects
    the browser back to the frontend settings page.
    """
    logger.info(
        f"GET /api/kite/callback request_token={'set' if request_token else 'missing'} status={status}"
    )

    if not request_token or status != "success":
        logger.warning("Kite callback — missing token or non-success status")
        return RedirectResponse(url=f"{_frontend_url()}/settings?kite=error")

    api_secret = _kite_api_secret()
    if not api_secret:
        logger.error("KITE_API_SECRET not set — cannot complete OAuth handshake")
        return RedirectResponse(url=f"{_frontend_url()}/settings?kite=error")

    try:
        kite = _get_kite()
        session_data = kite.generate_session(request_token, api_secret=api_secret)
        access_token: str = session_data["access_token"]
        kite.set_access_token(access_token)
        _save_kv(db, {
            "kite_access_token": access_token,
            "kite_token_date": str(date.today()),
        })
        logger.info("Kite access_token saved successfully")
        try:
            sync_result = _sync_holdings(db, kite)
            return RedirectResponse(
                url=(
                    f"{_frontend_url()}/settings"
                    f"?kite=connected&synced={sync_result['upserted']}&skipped={sync_result['skipped']}"
                )
            )
        except HTTPException as exc:
            logger.error(f"Kite callback sync failed after successful auth: {exc.detail}")
            return RedirectResponse(url=f"{_frontend_url()}/settings?kite=connected&sync=error")
    except Exception as exc:
        logger.error(f"Kite session generation failed: {exc}")
        return RedirectResponse(url=f"{_frontend_url()}/settings?kite=error")


@router.post("/sync")
def kite_sync(db: Session = Depends(get_db)) -> dict:
    """
    Fetch holdings from Kite and upsert them into the local portfolio.
    Only affects India/KITE broker holdings — US holdings are untouched.
    """
    logger.info("POST /api/kite/sync")

    token = _load_token(db)
    if not token:
        raise HTTPException(status_code=400, detail="Kite not connected. Complete OAuth flow first.")

    kite = _get_kite()
    kite.set_access_token(token)
    return _sync_holdings(db, kite)

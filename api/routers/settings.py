"""Settings router — read and update user preferences stored in SettingKV.

GET /api/settings     — return all settings
PUT /api/settings     — update one or more settings
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas.settings import BucketWeight, SettingsResponse, UpdateSettingsRequest
from pipeline.db.enums import Bucket
from pipeline.db.models import SettingKV

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Setting key names stored in SettingKV table
_KEYS = {
    "picks_per_bucket": 10,
    "rebalance_day": 7,
    "telegram_enabled": False,
    "stock_news_enabled": True,
    "shock_detection_enabled": True,
    "universe_nifty": "nifty500",
    "universe_sp": "sp500",
    "bucket_alloc_quality_value": 60.0,
    "bucket_alloc_quality_momentum": 40.0,
    "bucket_alloc_momentum": 0.0,
    "bucket_alloc_dividend_growth": 0.0,
}


@router.get("", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    kv = _load_all(db)
    return SettingsResponse(
        picks_per_bucket=int(kv.get("picks_per_bucket", 10)),
        bucket_allocations=[
            BucketWeight(bucket=Bucket.QUALITY_VALUE, allocation_pct=float(kv.get("bucket_alloc_quality_value", 60.0))),
            BucketWeight(bucket=Bucket.QUALITY_MOMENTUM, allocation_pct=float(kv.get("bucket_alloc_quality_momentum", 40.0))),
            BucketWeight(bucket=Bucket.MOMENTUM, allocation_pct=float(kv.get("bucket_alloc_momentum", 0.0))),
            BucketWeight(bucket=Bucket.DIVIDEND_GROWTH, allocation_pct=float(kv.get("bucket_alloc_dividend_growth", 0.0))),
        ],
        rebalance_day=int(kv.get("rebalance_day", 7)),
        telegram_enabled=_bool(kv.get("telegram_enabled", False)),
        stock_news_enabled=_bool(kv.get("stock_news_enabled", True)),
        shock_detection_enabled=_bool(kv.get("shock_detection_enabled", True)),
        universe_nifty=str(kv.get("universe_nifty", "nifty500")),
        universe_sp=str(kv.get("universe_sp", "sp500")),
    )


@router.put("", response_model=SettingsResponse)
def update_settings(
    body: UpdateSettingsRequest,
    db: Session = Depends(get_db),
) -> SettingsResponse:
    updates: dict[str, str] = {}

    if body.picks_per_bucket is not None:
        updates["picks_per_bucket"] = str(body.picks_per_bucket)
    if body.rebalance_day is not None:
        updates["rebalance_day"] = str(body.rebalance_day)
    if body.telegram_enabled is not None:
        updates["telegram_enabled"] = str(body.telegram_enabled)
    if body.stock_news_enabled is not None:
        updates["stock_news_enabled"] = str(body.stock_news_enabled)
    if body.shock_detection_enabled is not None:
        updates["shock_detection_enabled"] = str(body.shock_detection_enabled)
    if body.universe_nifty is not None:
        updates["universe_nifty"] = body.universe_nifty
    if body.universe_sp is not None:
        updates["universe_sp"] = body.universe_sp
    if body.bucket_allocations:
        _bucket_key = {
            Bucket.QUALITY_VALUE: "bucket_alloc_quality_value",
            Bucket.QUALITY_MOMENTUM: "bucket_alloc_quality_momentum",
            Bucket.MOMENTUM: "bucket_alloc_momentum",
            Bucket.DIVIDEND_GROWTH: "bucket_alloc_dividend_growth",
        }
        for bw in body.bucket_allocations:
            key = _bucket_key.get(bw.bucket)
            if key:
                updates[key] = str(bw.allocation_pct)

    _save_all(db, updates)
    return get_settings(db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_all(db: Session) -> dict[str, str]:
    rows = db.execute(select(SettingKV)).scalars().all()
    kv = {r.key: r.value for r in rows}
    # Merge with defaults for any missing keys
    for k, v in _KEYS.items():
        kv.setdefault(k, str(v))
    return kv


def _save_all(db: Session, updates: dict[str, str]) -> None:
    for key, value in updates.items():
        row = db.execute(select(SettingKV).where(SettingKV.key == key)).scalar_one_or_none()
        if row is None:
            db.add(SettingKV(key=key, value=value))
        else:
            row.value = value
    db.commit()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")

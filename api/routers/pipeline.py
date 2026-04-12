"""Pipeline router — trigger a rebalance run on demand.

POST /api/pipeline/run   — run the full monthly pipeline in a background thread
GET  /api/pipeline/status — last run date + status
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from pipeline.db.models import RebalanceSnapshot

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# Simple in-process flag — good enough for a single-user local app
_run_state: dict = {"running": False, "last_error": None}


@router.post("/run", status_code=202)
def trigger_run(
    background_tasks: BackgroundTasks,
    fresh_capital: float = Query(0.0, description="Fresh capital to deploy"),
    picks: int = Query(10, ge=5, le=20),
) -> dict:
    """Trigger the full monthly rebalance pipeline asynchronously."""
    if _run_state["running"]:
        return {"status": "already_running", "message": "Pipeline is already running."}

    background_tasks.add_task(_run_pipeline_bg, fresh_capital=fresh_capital, picks=picks)
    return {"status": "started", "message": "Pipeline run started in background."}


@router.get("/status")
def pipeline_status(db: Session = Depends(get_db)) -> dict:
    """Return last completed run date and current running state."""
    snapshot = db.execute(
        select(RebalanceSnapshot).order_by(RebalanceSnapshot.run_date.desc()).limit(1)
    ).scalar_one_or_none()

    return {
        "running": _run_state["running"],
        "last_run_date": str(snapshot.run_date) if snapshot else None,
        "last_error": _run_state["last_error"],
    }


def _run_pipeline_bg(fresh_capital: float, picks: int) -> None:
    """Called in a background thread — runs the full pipeline."""
    _run_state["running"] = True
    _run_state["last_error"] = None
    try:
        from pipeline.scheduler import run_pipeline
        run_pipeline(fresh_capital=fresh_capital, picks_per_bucket=picks)
    except Exception as exc:  # noqa: BLE001
        _run_state["last_error"] = str(exc)
    finally:
        _run_state["running"] = False

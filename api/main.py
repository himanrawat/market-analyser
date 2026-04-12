"""FastAPI application entry point.

Run locally:
    uvicorn api.main:app --reload --port 8000

The API is intentionally thin — it reads from SQLite populated by the pipeline
and exposes clean JSON endpoints for the Next.js frontend to consume.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pipeline.db import init_db
from pipeline.logging_setup import configure_logging

from api.routers import (
    actions,
    dashboard,
    journal,
    news,
    pipeline,
    portfolio,
    ranked,
    settings,
    stocks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before the first request."""
    configure_logging()
    init_db()   # idempotent — creates tables if they don't exist yet
    yield


app = FastAPI(
    title="Market Analyser API",
    description="Personal stock-picker & monthly rebalance tool — API layer.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server and production origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Next.js dev
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(dashboard.router)
app.include_router(ranked.router)
app.include_router(actions.router)
app.include_router(stocks.router)
app.include_router(portfolio.router)
app.include_router(journal.router)
app.include_router(news.router)
app.include_router(settings.router)
app.include_router(pipeline.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "market-analyser-api"}

# Market Analyser

Personal stock picker and monthly rebalance tool for Nifty 500 + S&P 500.

The app combines:
- A Python pipeline for market data ingestion, scoring, guardrails, portfolio diffing, news/shock detection, and notifications.
- A FastAPI backend that serves the SQLite-backed data model.
- A Next.js frontend for ranked lists, stock detail, portfolio tracking, action execution, journal review, news, and settings.

The product spec lives in [PRD.md](PRD.md).

## Current Status

The project is now a working full-stack baseline rather than a Phase 1 stub:
- Backend test suite passes.
- Frontend production build passes.
- Phase 4 flows are fully wired end-to-end.
- The monthly pipeline now persists real rebalance snapshots, so `/api/actions` and `/api/ranked` work after a completed run.
- FMP-backed stock detail enrichments now include analyst forecasts, EPS estimates, live peers, and richer event/news fallback behavior.

Implementation details and PRD mapping are documented in [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).

## Core Features

- Ranked monthly lists across 4 buckets and 2 markets
- Guardrails, regime flags, and browse-vs-actionable separation
- Stock detail pages with score breakdown, sentiment, events, holding data, analyst forecasts, EPS estimates, and peer comparison
- Portfolio CRUD with current value, sector allocation, and LTCG warning
- Action planner with bucket allocations, live quote refresh, skip-month logging, and executed-trade flow
- Trade journal with exit lessons and monthly review summaries
- News feed and shock banner support
- Settings for rebalance day, universes, capital defaults, and notification toggles

## Architecture

### Backend

- `pipeline/`
  Handles providers, caching, universe loading, scoring, portfolio diffing, sentiment/shock logic, scheduling, and notifications.
- `api/`
  Thin FastAPI layer over the SQLite database and pipeline entrypoints.
- `data/market.db`
  Local SQLite store for prices, fundamentals, scores, snapshots, holdings, journal, settings, and shock events.

### Frontend

- `frontend/src/app/`
  App Router pages for dashboard, ranked lists, actions, portfolio, journal, news, stock detail, and settings.
- `frontend/src/lib/api.ts`
  Frontend adapter layer that normalizes backend responses so UI pages stay stable.

## Quick Start

### 1. Backend setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in at least:
- `FMP_API_KEY`
- `FRED_API_KEY`
- `NEWSAPI_KEY` if you want the fallback news lane
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` if you want Telegram notifications

### 2. Frontend setup

```bash
cd frontend
npm install
cp .env.local.example .env.local 2>/dev/null || true
```

If `frontend/.env.local` already exists, make sure it points at the API:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Run the API

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

### 4. Run the frontend

```bash
cd frontend
npm run dev
```

Open:
- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

## Useful Commands

### Run the monthly pipeline manually

```bash
source .venv/bin/activate
python -m pipeline.cli run
```

Important:
- The Actions and Ranked pages require at least one completed rebalance snapshot.
- If the API returns `No rebalance snapshot found. Run the pipeline first.`, the pipeline has not completed successfully yet.

### FMP free-plan behavior

- Core price/fundamental/profile flows work with `yfinance` fallback where appropriate.
- Stock-detail forecast and peer tabs will now explain when an FMP endpoint is unavailable on the current plan instead of silently appearing empty.
- General market news falls back to `NewsAPI` when FMP general news is unavailable.
- Some stock-specific enrichment still depends on whether your FMP plan exposes that endpoint for the symbol you are viewing.

### Run the full backend test suite

```bash
source .venv/bin/activate
./.venv/bin/pytest
```

### Build the frontend

```bash
cd frontend
./node_modules/.bin/next build --webpack
```

`--webpack` is included here because it is the most reliable production-build path in restricted environments.

## Verification

Latest verification from this repo state:

```bash
./.venv/bin/pytest
./node_modules/.bin/next build --webpack
```

Both passed in the current workspace.

## Repo Layout

```text
api/                 FastAPI routers + response schemas
pipeline/            Providers, scoring, portfolio logic, notifications, scheduler
frontend/            Next.js application
tests/               Pytest coverage across API, providers, scoring, news, schema, and universe
config/              Tunable config and weights
data/                SQLite DB and cache artifacts
logs/                Pipeline logs
docs/                Project documentation and implementation notes
```

## Documentation

- [PRD.md](PRD.md)
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)
- [frontend/README.md](frontend/README.md)

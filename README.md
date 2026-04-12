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
- Hybrid India fundamentals rollout has started: the backend now has an official-source India lane that can sit in front of vendor fundamentals and merge missing fields from vendor data when needed.

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
- Hybrid India fundamentals routing: official-source imports first for India, vendor merge/fallback after that, FMP remaining primary for US

## Architecture

### Backend

- `pipeline/`
  Handles providers, caching, universe loading, scoring, portfolio diffing, sentiment/shock logic, scheduling, notifications, and the hybrid India fundamentals lane.
- `api/`
  Thin FastAPI layer over the SQLite database and pipeline entrypoints.
- `data/market.db`
  Local SQLite store for prices, fundamentals, scores, snapshots, holdings, journal, settings, and shock events.
- `data/official_india/`
  Optional local import lane for official NSE/BSE India fundamentals and shareholding files used by the hybrid provider.

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

Optional:
- `OFFICIAL_INDIA_DATA_DIR` if you want the hybrid India provider to read official-source files from a custom location

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

### Import official India files into the hybrid lane

```bash
source .venv/bin/activate
python -m pipeline.cli import-india-official \
  --ticker RELIANCE \
  --source nse \
  --financials /path/to/downloaded-financials.csv \
  --shareholding /path/to/downloaded-shareholding.csv
```

This writes canonical JSON under `data/official_india/nse/...`, which the hybrid India provider reads automatically.

### Fetch live NSE data into the hybrid lane

```bash
source .venv/bin/activate
python -m pipeline.cli fetch-india-official \
  --ticker RELIANCE \
  --limit 8 \
  --statement-scope consolidated
```

This fetches live NSE quarterly financial-result rows plus shareholding rows and writes canonical JSON under `data/official_india/nse/...`.

### Fetch a starter India basket in one command

```bash
source .venv/bin/activate
python -m pipeline.cli fetch-india-official-batch \
  RELIANCE TCS INFY ITC HINDUNILVR \
  --limit 8 \
  --statement-scope consolidated
```

This is the fastest way to warm the hybrid lane for the initial India basket before a wider rollout.

Important:
- The Actions and Ranked pages require at least one completed rebalance snapshot.
- If the API returns `No rebalance snapshot found. Run the pipeline first.`, the pipeline has not completed successfully yet.

### FMP free-plan behavior

- US price/fundamental/profile flows work with `yfinance` fallback where appropriate.
- India fundamentals are no longer treated as a vendor-only lane in the target architecture. The hybrid provider can read official NSE/BSE files first, then merge or fall back to vendor data.
- Stock-detail forecast and peer tabs will now explain when an FMP endpoint is unavailable on the current plan instead of silently appearing empty.
- General market news falls back to `NewsAPI` when FMP general news is unavailable.
- Some stock-specific enrichment still depends on whether your FMP plan exposes that endpoint for the symbol you are viewing.

## Hybrid India Fundamentals

What changed:
- Removed: `FMP` as the assumed source of truth for Indian quarterly fundamentals.
- Removed: `yfinance` as the intended long-term India fundamentals source.
- Replaced with: `official NSE files -> BSE fallback files -> vendor merge/fallback`.
- Added: local India ratio computation and promoter-holding ingestion hooks.

Current implementation slice:
- The backend can now look for official India files under `data/official_india/` before calling vendor fundamentals for Indian tickers.
- If official India data exists but is missing fields like valuation ratios, vendor snapshots can still fill those gaps.
- If no official India data is present yet, the existing vendor path continues to work.
- A CLI importer now normalizes downloaded NSE/BSE CSV/JSON files into the canonical layout consumed by the provider.
- A live NSE fetcher can now pull quarterly financial-result detail rows and shareholding master rows directly into that canonical layout.
- The monthly pipeline can now backfill missing India official files gradually for `Nifty 500`, prioritizing `RELIANCE`, `TCS`, `INFY`, `ITC`, and `HINDUNILVR` first.

Supported file layout for the first hybrid slice:

```text
data/official_india/
  nse/
    financials/
      RELIANCE.json
    shareholding/
      RELIANCE.json
  bse/
    financials/
      RELIANCE.json
  financials/
    RELIANCE.csv
```

The initial parser accepts JSON or CSV rows keyed by ticker and normalizes them into the existing `FundamentalSnapshot` shape used by the scoring engine and API.

Current live NSE limitation:
- The fetcher currently imports quarterly filing metadata, promoter/shareholding rows, and the filing-detail P&L fields exposed by NSE.
- Full balance-sheet/cash-flow/XBRL parsing is still a later step, so some ratios may still need vendor enrichment or remain unavailable.
- Vendor enrichment is now silent when official India data already succeeded, so the pipeline no longer emits noisy fallback warnings for that path.

Relevant runtime knobs:

```text
OFFICIAL_INDIA_AUTO_FETCH_ENABLED=true
OFFICIAL_INDIA_AUTO_FETCH_BATCH_SIZE=5
OFFICIAL_INDIA_AUTO_FETCH_LIMIT=8
OFFICIAL_INDIA_AUTO_FETCH_STATEMENT_SCOPE=consolidated
```

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
data/                SQLite DB, cache artifacts, and optional official India imports
logs/                Pipeline logs
docs/                Project documentation and implementation notes
```

## Documentation

- [PRD.md](PRD.md)
- [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md)
- [frontend/README.md](frontend/README.md)

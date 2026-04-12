# Market Analyser

Personal stock picker & monthly rebalance tool for Nifty 500 + S&P 500.
Rules-based scoring across 4 investment buckets. Local, single-user, cheap.

See [PRD.md](PRD.md) for the full spec.

## Status

Phase 1 — Data Foundation (Python pipeline). In progress.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Fill in FMP_API_KEY, FRED_API_KEY, etc.
```

## Layout

```
pipeline/           Python data pipeline (Phase 1)
  config.py         Settings loaded from .env
  db/               SQLAlchemy models + session
  providers/        yfinance, FMP, FRED, NewsAPI abstractions
  universe/         Constituent loader + hard filters
  scoring/          4-bucket scoring engine
  portfolio/        Diff engine (BUY/SELL/ADD/TRIM/HOLD)
  news/             Sentiment + shock detector
  notify/           Telegram digest
config/             events.yaml, tunable weights
data/               SQLite DB + snapshots (gitignored)
logs/               Pipeline logs (gitignored)
tests/              Pytest suite
```

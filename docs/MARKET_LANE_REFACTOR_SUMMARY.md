# Market Lane Refactor Summary

Date: April 13, 2026

This document summarizes the India/US market-lane cleanup and separation work completed in this refactor pass.

## What Was Removed

No core market code file was deleted from the repo, but these runtime paths and assumptions were removed:

- India stock detail no longer instantiates `FMPProvider` directly.
- `FMPProvider` is no longer valid for India market/stocks/fundamentals usage. It is now US-only by design.
- The placeholder country filter in guardrails was removed. `ScoreOutput` now carries `country`, and guardrails/actions/diff logic use it directly.
- The broken refresh-prices call path using `provider.prices(ticker)` was removed and replaced with the routed `get_latest_quote(...)` flow.
- The old action-plan key shape `<ticker>|<bucket>` was removed from runtime planning in favor of `<ticker>|<country>|<bucket>`, which avoids India/US collisions for the same ticker.
- Old mixed-market assumptions based on ticker-only identity were removed from guardrails, portfolio diff, and action reconstruction.

## What Was Added

- `pipeline/providers/india_market_provider.py`
  Official India runtime provider for:
  - NSE latest quote parsing
  - NSE equity metadata/profile enrichment
  - NSE corporate announcements as India stock news
  - NSE board meetings + corporate actions as India events

- `pipeline/providers/us_market_provider.py`
  Explicit US-only wrapper for:
  - FMP primary profile/fundamentals
  - yfinance fallback for US profile/fundamentals
  - US-only forecasts, peers, stock news, and events

- India stock master identifiers persisted on `stocks`:
  - `isin`
  - `nse_symbol`
  - `bse_symbol`
  - `bse_scripcode`

- SQLite compatibility upgrade in `pipeline/db/base.py`
  Existing local DBs now get the new stock identifier columns added automatically on `init_db()`.

- NSE runtime endpoint support in `pipeline/importers/india_official.py` for:
  - `quote-equity`
  - `corporate-announcements`
  - `corporate-board-meetings`
  - `corporate-actions`

- Stock detail response fields for India identifiers:
  - `isin`
  - `nse_symbol`
  - `bse_symbol`
  - `bse_scripcode`

## What Was Separated

### Provider layer

- `pipeline/providers/registry.py` now routes by market lane instead of mixing shared FMP/yfinance logic everywhere.
- India lane:
  - fundamentals: official India files first, yfinance fallback only
  - profile: official NSE metadata first, yfinance fallback for missing static fields
  - stock news: official NSE corporate announcements
  - events: official NSE board meetings and corporate actions
  - latest quote: official NSE quote first, yfinance fallback
- US lane:
  - fundamentals/profile: `FMP -> yfinance`
  - forecasts/peers/news/events: US-only vendor lane

### API layer

- `api/routers/stocks.py` now follows separate India and US stock-detail behavior:
  - India:
    - no FMP usage
    - official NSE live news/events
    - local same-sector peers only
    - forecasts intentionally disabled with an explicit note
  - US:
    - US-only `USMarketProvider` handles forecasts and peers

- `api/routers/actions.py` now refreshes prices through the routed provider service and uses country-aware action keys.

### Scoring / ranking / diff layer

- `pipeline/scoring/base.py`
  `ScoreOutput` now carries `country`.

- `pipeline/scoring/guardrails.py`
  Country filtering is now real, not placeholder logic.

- `pipeline/portfolio/diff.py`
  Holdings and scores are matched by `(ticker, country)` instead of ticker only.

- `api/routers/ranked.py`
  Ranked-list explainability now reconstructs `ScoreOutput` with country attached.

## Files In Use For What

Only the code files related to market, stocks, and fundamentals are listed below.

- `pipeline/providers/india_market_provider.py`
  India runtime market lane for official NSE quote/profile/news/event data.

- `pipeline/providers/india_official_provider.py`
  India official fundamentals reader from canonical on-disk NSE/BSE files.

- `pipeline/providers/us_market_provider.py`
  US runtime wrapper for FMP primary and yfinance fallback behavior.

- `pipeline/providers/registry.py`
  Main market-aware data facade used by pipeline and API routes.

- `pipeline/providers/fmp_provider.py`
  US-only FMP implementation.

- `pipeline/providers/yfinance_provider.py`
  Shared price-history provider, macro market indicators, and fallback profile/fundamentals where allowed.

- `pipeline/providers/rbi_provider.py`
  India macro lane.

- `pipeline/providers/fred_provider.py`
  US macro lane.

- `pipeline/importers/india_official.py`
  India official importer plus live NSE client used for canonical official data and NSE runtime endpoints.

- `pipeline/universe/sources.py`
  Universe constituent fetchers for Nifty and S&P sources.

- `pipeline/universe/loader.py`
  Syncs constituent files into the stock master and persists identifiers/profile fields.

- `pipeline/db/models.py`
  Canonical `Stock`, `Fundamental`, `Price`, `Event`, and related ORM models.

- `pipeline/db/base.py`
  DB initialization plus local SQLite schema-upgrade support for new stock identifier columns.

- `pipeline/scoring/base.py`
  Core scoring input/output types, including country-aware `ScoreOutput`.

- `pipeline/scoring/buckets.py`
  Bucket scoring logic for fundamentals/quality/momentum/dividend factors.

- `pipeline/scoring/guardrails.py`
  Country-aware guardrails, sector cap, blackout, and regime handling.

- `pipeline/scheduler.py`
  Pipeline orchestrator that pulls market data, fundamentals, events, and news through the separated lanes.

- `pipeline/portfolio/diff.py`
  Country-aware action generation from ranked lists versus holdings.

- `pipeline/portfolio/planner.py`
  Capital allocation planner using country-aware action keys.

- `api/routers/stocks.py`
  Stock detail API route with separate India and US enrichment behavior.

- `api/routers/ranked.py`
  Ranked-stock API response assembly.

- `api/routers/actions.py`
  Action planner and refresh-prices API route.

- `api/schemas/stocks.py`
  Stock detail response schema.

- `api/schemas/actions.py`
  Action planner response schema.

## Phase 1 — India-Only Detach (April 13, 2026)

After the lane separation was completed, the US runtime was explicitly detached for Phase 1:

| File | Change |
| --- | --- |
| `pipeline/universe/loader.py` | `DEFAULT_INDEXES` reduced to `[NIFTY_500]` |
| `pipeline/scheduler.py` | US macro series not fetched; snapshot fields written as `None` |
| `pipeline/scoring/guardrails.py` | `compute_macro_regime` uses Nifty 50 only; SP params renamed `_sp_close`/`_sp_200dma` |
| `frontend/src/app/page.tsx` | US VIX card, Fed Funds Rate, US CPI YoY commented out |
| `frontend/src/components/MacroHeader.tsx` | US VIX chip commented out |
| `frontend/src/app/ranked/page.tsx` | "Both markets" and "US only" options commented out |

All commented code is marked `// Phase 2 (US market)` or `# Phase 2 (US market)` for easy recovery.

## Important Remaining Gaps

These are still not completed by this refactor:

- Live BSE runtime client support is still not implemented.
- India daily historical price history is still yfinance-backed; official bhavcopy/archive ingestion is still pending.
- India derivatives, bulk/block deals, insider disclosures, and structured disclosure parsing are still pending.
- India forecasts/peer-mapping are intentionally not faked; they remain unavailable until there is an India-appropriate lane for them.

# US Market Status

Status: `Detached — Phase 2`

This document tracks the current US market implementation in the workspace as of April 13, 2026.

The US lane code exists and is correct, but it is **fully detached from the active runtime** for Phase 1. The product is India-only until the India market lane is completed end-to-end. US work will resume as Phase 2.

## What Is Detached (Phase 1)

These runtime paths are explicitly disabled or stubbed until Phase 2:

| Location | What is detached |
| --- | --- |
| `pipeline/universe/loader.py` | `DEFAULT_INDEXES` is `[NIFTY_500]` only — `SP_500` is commented out |
| `pipeline/scheduler.py` | `US_VIX`, `SP_500`, `FEDFUNDS`, `US_10Y`, `US_CPI_YOY` macro series are not fetched; values written as `None` |
| `pipeline/scoring/guardrails.py` | `compute_macro_regime` uses Nifty 50 only; SP 500 params are `_sp_close`/`_sp_200dma` (reserved, unused) |
| `frontend/src/app/page.tsx` | US VIX card, Fed Funds Rate, and US CPI YoY macro cards are commented out |
| `frontend/src/components/MacroHeader.tsx` | US VIX chip is commented out |
| `frontend/src/app/ranked/page.tsx` | "Both markets" and "US only" filter options are commented out |

To re-enable the US lane in Phase 2: restore the commented-out lines in each location above and remove the `_` prefix from `_sp_close`/`_sp_200dma` in `guardrails.py`.

## Current US Scope

What is already working for the US market:

- `S&P 500` universe support is implemented.
- US price history and latest quote refresh are implemented.
- US fundamentals and profile routing are implemented with `FMP` primary and `yfinance` fallback.
- US macro ingestion is implemented through `FRED` plus market indicators from `yfinance`.
- US stock detail pages can show analyst forecasts, EPS estimates, peers, stock news, and upcoming events when the provider plan allows.
- Ranked lists, actions, portfolio, journal, dashboard, and settings already support US stocks.
- Tests already cover provider, API, and scheduler behavior for the US lane.

## Relevant Files

| File | What is completed | What is still remaining / note |
| --- | --- | --- |
| `docs/PRD.md` | Defines the US scope: `S&P 500`, vendor-backed fundamentals, macro, ranked lists, actions, and portfolio workflow. | Update only when US work resumes. |
| `docs/IMPLEMENTATION_STATUS.md` | Confirms the current app works end-to-end and that US functionality remains in place. | Keep aligned later when US enhancements restart. |
| `docs/FMP_API_DOC.md` | Archived reference for the US vendor lane. | Refresh only when the US roadmap becomes active again. |
| `pipeline/universe/sources.py` | Fetches `S&P 500` and derived `S&P 100` constituents from the public `SPY` holdings file. | Could later be upgraded if exact index-source fidelity becomes more important. |
| `pipeline/universe/loader.py` | Syncs US constituents into the DB and backfills missing stock profiles. | Could later reduce dependence on vendor profile backfill. |
| `pipeline/universe/filter.py` | Applies the US hard filters, including the `$2B` market-cap floor and `$10M` average daily traded value floor. | No major gap, but future US-specific exclusions can be added later. |
| `pipeline/scoring/buckets.py` | Shared 4-bucket scoring already works for US stocks, including the US dividend-growth threshold logic. | US-only factor packs are not built yet. |
| `pipeline/providers/fmp_provider.py` | Implements US profile, quarterly fundamentals, stock news, general news, analyst forecasts, peers, and upcoming events. | Still a single-vendor dependency for several US detail surfaces. |
| `pipeline/providers/yfinance_provider.py` | Provides US OHLCV, latest quotes, fallback profile, fallback fundamentals, and some macro indicators. | No second dedicated US price source yet beyond `yfinance`. |
| `pipeline/providers/fred_provider.py` | Provides Fed funds, US CPI, GDP growth, unemployment, US 10Y, and US VIX. | More US macro breadth can be added later. |
| `pipeline/providers/newsapi_provider.py` | Gives a fallback lane for general market news when `FMP` general news is unavailable. | It does not replace stock-specific US news. |
| `pipeline/providers/registry.py` | Routes US fundamentals/profile through `FMP -> yfinance` fallback and keeps the US lane operational. | Could later be split into a more explicit `us_market` package. |
| `pipeline/scheduler.py` | Runs the US lane end-to-end inside the monthly pipeline. | No active US-specific enhancement batch is being added while work is on hold. |
| `api/routers/stocks.py` | Builds the US stock detail response, including forecasts, peers, news, and events. | Live enrichments are still provider-dependent at request time. |
| `api/routers/ranked.py` | Returns ranked US lists and supports country, sector, and valuation sorting. | `earnings_soon` and `recent_earnings_beat` are still placeholder fields. |
| `api/routers/actions.py` | Supports US action planning, execution logging, and refresh-prices flow. | Broker execution remains manual by design. |
| `frontend/src/lib/api.ts` | Normalizes US backend responses for the frontend. | Additional US-only fields can be added later without touching every page. |
| `frontend/src/app/page.tsx` | Dashboard already shows macro and market data used by the US lane. | No US-specific dashboard expansion is active right now. |
| `frontend/src/app/ranked/page.tsx` | Ranked UI already supports `US only` filtering and valuation sorts. | More US-specific badges depend on deeper backend enrichment. |
| `frontend/src/app/stocks/[ticker]/page.tsx` | US stock detail UI already renders overview, scores, chart, news, events, forecasts, and peers. | Any future US-only analytics need backend data first. |
| `frontend/src/app/actions/page.tsx` | Action planner works for US names alongside India. | No broker automation is planned in `v1`. |
| `frontend/src/app/portfolio/page.tsx` | Portfolio UI already supports US holdings and allocation breakdown. | CSV/broker import is still deferred. |
| `frontend/src/app/settings/page.tsx` | Settings already expose the US universe selection. | Additional US strategy controls are not active. |
| `tests/test_providers.py` | Covers mocked US `FMP` and `yfinance` provider behavior. | Could later add more live-smoke coverage. |
| `tests/test_api.py` | Covers API behavior with US stocks seeded in the test DB. | More US-specific edge cases can be added later. |
| `tests/test_scheduler.py` | Verifies the pipeline can persist a full snapshot using a US stock. | Does not replace real-provider integration tests. |

## What We Have Completed

- Built the US lane into the same working product flow as India.
- Implemented US universe loading, filtering, scoring, snapshot persistence, ranked lists, actions, portfolio tracking, and journal flow.
- Integrated US macro data with `FRED`.
- Integrated US stock-detail enrichment with `FMP` for forecasts, peers, events, and news when available.
- Added graceful fallback behavior with `yfinance` and `NewsAPI` where practical.
- Covered the US lane in automated tests and in the verified app build/status documentation.

## What Is Remaining

These are the main items left once US work resumes:

- Reduce single-vendor dependency for analyst forecasts, peers, stock-specific news, and events.
- Add richer US macro and market-breadth factors such as yield-curve shape, credit spreads, sector breadth, and earnings-revision breadth.
- Improve ranked-list event intelligence so `earnings_soon` and related fields are fully populated instead of placeholder values.
- Decide whether the `SPY` holdings file remains good enough as the long-term constituent source or whether a more exact US universe source is needed.
- Add stronger live/integration coverage for plan-limited `FMP` behavior and fallback quality.
- Extend the stock-detail and ranking experience only after the India lane is no longer the top priority.

## Hold Note

The US market lane should be treated as `stable but paused`.

That means:

- keep bug fixes and regressions safe,
- do not remove existing US functionality,
- do not start feature expansion until the India market implementation is finished.

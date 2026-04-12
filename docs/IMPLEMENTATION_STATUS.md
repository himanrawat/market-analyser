# Implementation Status

This document maps the current codebase to the product requirements in [PRD.md](../PRD.md).

## Summary

The repo now ships as a working single-user full-stack application with:
- data pipeline
- SQLite persistence
- FastAPI API layer
- Next.js frontend
- portfolio/actions/journal execution loop
- news and shock surfaces
- live FMP-backed stock-detail enrichment where available
- hybrid India fundamentals routing support via official-source imports plus vendor merge/fallback
- automated tests and production frontend build verification

## Phase Status

### Phase 1: Data foundation

Implemented:
- SQLite schema and models
- FMP, yfinance, FRED, RBI, NewsAPI, and official-India provider abstractions
- caching layer
- universe ingestion support
- pipeline sync for prices, fundamentals, events, macro snapshots, and general market news
- first hybrid India fundamentals slice:
  - official India file-backed provider
  - India-first routing in the registry
  - vendor merge/fallback when official data is partial or absent
  - CLI importer for downloaded NSE/BSE financial/shareholding files
  - live NSE fetch command for quarterly financial-result detail rows plus shareholding master rows

### Phase 2: Scoring engine

Implemented:
- 4 bucket scoring engine
- universe filtering
- guardrails
- macro regime support
- snapshot persistence

### Phase 3: Frontend foundation

Implemented:
- dashboard shell
- ranked lists
- stock detail pages
- live analyst forecasts, EPS estimate rows, richer peers, and event/news fallback on stock detail
- manual filter/sort support on ranked lists

### Phase 4: Portfolio + actions

Implemented end-to-end:
- manual portfolio entry and editing
- portfolio diff logic
- capital deployment planner
- refresh prices
- skip this month
- mark-as-executed flow
- trade journal creation and review

### Phase 5: News, shock detection, polish

Implemented baseline:
- news feed route and page
- shock banner route and header/banner integration
- settings UI and persistence
- manual pipeline trigger

Provider-dependent enrichment still degrades gracefully when data is unavailable:
- analyst forecast endpoints on free / restricted FMP plans
- peer endpoint fallback to same-sector local comparison if provider lookup is unavailable
- official India fundamentals fall back to the existing vendor lane when no official import exists yet

## Key Working Flows

### Monthly rebalance flow

1. Run the pipeline.
2. Open ranked lists.
3. Open actions.
4. Set fresh capital and bucket allocation.
5. Refresh prices if desired.
6. Execute rows from the action table.
7. Review the resulting journal entries.

### Portfolio maintenance flow

1. Open portfolio.
2. Add or edit holdings.
3. Review sector allocation and LTCG warning.

### News and shock flow

1. Open news for stock/general feeds.
2. Review the top shock banner from the dashboard shell if active.

## Verification State

Verified against the current workspace with:

```bash
./.venv/bin/pytest
./node_modules/.bin/next build --webpack
```

Result:
- `212 passed, 3 deselected`
- frontend production build passed

## Known Graceful Fallbacks

These do not break the application, but they are useful to know during review:

- Stock-detail forecasts now load from FMP when available, but free-plan restrictions can still return a structured “plan limited” message.
- Peer comparison prefers FMP peers and falls back to same-sector local data when provider lookup is unavailable.
- Monthly review win-rate and biggest winner/loser depend on richer closed-trade history and may show empty values.
- Stock-specific news is still best-effort: the pipeline persists general market news, while individual stock pages can pull live stock news if the provider endpoint is available.
- The hybrid India lane currently expects official-source files under `data/official_india/`; live NSE/BSE fetchers are not fully built yet.
- Downloaded official files can now be normalized into that layout with `python -m pipeline.cli import-india-official ...`.
- NSE can now populate that layout directly with `python -m pipeline.cli fetch-india-official ...`, but the live slice currently focuses on quarterly P&L detail and shareholding rows rather than full XBRL statement extraction.
- A batch command now exists for the starter India basket: `python -m pipeline.cli fetch-india-official-batch RELIANCE TCS INFY ITC HINDUNILVR ...`.
- The scheduler now backfills missing India official files gradually during pipeline runs, prioritizing the starter basket first and then continuing through the wider `Nifty 500`.
- Vendor enrichment remains optional, but its failure is now silent when official India data already succeeded.

## Reviewer Notes

- The frontend uses an adapter layer in `frontend/src/lib/api.ts` to normalize backend responses and prevent runtime schema drift.
- The production frontend build is verified with webpack because it is the most stable path in restricted environments.
- The scheduler is now covered by a dedicated test that exercises a mocked end-to-end monthly run and verifies snapshot persistence.

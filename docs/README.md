# Documentation Index

This directory is the single home for the project documentation.

Current execution priority:
- **Phase 1 (active): India market only** — Nifty 500 universe, India fundamentals, India macro, India news and events
- **Phase 2 (not started): US market** — S&P 500 universe, US macro (FRED), US fundamentals (FMP), US news and events

The US lane code exists in the codebase but is deliberately detached from the active runtime:
- `DEFAULT_INDEXES` in the pipeline is India-only
- US macro indicators are not fetched during pipeline runs
- Macro regime is computed from Nifty 50 alone
- US VIX, Fed Funds Rate, and US CPI cards are commented out of the frontend
- "US only" ranked-list filter is commented out of the frontend

## Core docs

- [PRD.md](./PRD.md)
  Product requirements and source-of-truth scope.
- [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md)
  Current codebase state, PRD mapping, and verification notes.
- [US_MARKET_STATUS.md](./US_MARKET_STATUS.md)
  Current US market implementation, relevant files, completed scope, remaining work, and the explicit on-hold status.
- [INDIA_DATA_LANE_IMPLEMENTATION.md](./INDIA_DATA_LANE_IMPLEMENTATION.md)
  India-first implementation plan for `NSE -> BSE -> Yahoo` with FMP removed from India-specific logic.
- [INDIA_MARKET_IMPROVEMENT_PLAN.md](./INDIA_MARKET_IMPROVEMENT_PLAN.md)
  India market completion status plus the next improvements needed for better analysis quality and data correctness.
- [MARKET_LANE_REFACTOR_SUMMARY.md](./MARKET_LANE_REFACTOR_SUMMARY.md)
  Summary of what was removed, added, and separated while refactoring the India and US market lanes.
- [FRONTEND.md](./FRONTEND.md)
  Frontend-specific notes and local run guidance.

## Reference docs

- [FMP_API_DOC.md](./FMP_API_DOC.md)
  Archived reference material for the US lane. Kept for later use when US work resumes.

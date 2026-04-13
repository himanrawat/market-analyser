# India Market Improvement Plan

This document builds on [INDIA_DATA_LANE_IMPLEMENTATION.md](./INDIA_DATA_LANE_IMPLEMENTATION.md).

The goal here is practical: capture what is already completed for the Indian market, what is still left, and which improvements will most increase data correctness and investing usefulness.

## Current India Scope

What is already completed:

- The repo has an official India fundamentals lane on disk under `data/official_india/`.
- `NSE` financial-result rows and shareholding rows can already be fetched live and normalized.
- The provider layer already reads official India files first for fundamentals.
- The provider can compute missing India ratios locally from imported rows.
- The scheduler can gradually warm missing India official data during pipeline runs.
- The existing API and frontend can already consume India data through the normalized response layer.

## Relevant Files

| File | What is completed | What is still left |
| --- | --- | --- |
| `docs/INDIA_DATA_LANE_IMPLEMENTATION.md` | Defines the India-first target architecture: `NSE -> BSE -> Yahoo`. | Still the main implementation reference until the lane is finished. |
| `docs/PRD.md` | Captures the product requirement that India should prefer official sources and compute local ratios. | Needs no major change yet; execution is still catching up to the PRD. |
| `pipeline/providers/india_official_provider.py` | Reads official India files and computes many derived fields locally such as `ROE`, `ROCE`, `debt_equity`, margins, `P/E`, `P/B`, and `FCF`. | It still depends on the quality and completeness of imported files; live BSE and richer official price/event inputs are missing. |
| `pipeline/importers/india_official.py` | Imports downloaded NSE/BSE files and already supports live `NSE` fetch for quarterly financial rows plus shareholding rows. | `BSE` is not yet implemented as a live automatic fetch client. |
| `pipeline/providers/registry.py` | Routes India fundamentals to official files first and then uses `yfinance` only for merge/fallback. | India prices, profile metadata, and some other surfaces still rely on `yfinance` or shared vendor flows. |
| `pipeline/providers/yfinance_provider.py` | Still keeps the India lane usable for prices, latest quotes, fallback profile, and fallback fundamentals. | This should become the emergency fallback only, not the normal India runtime path. |
| `pipeline/scheduler.py` | Gradually backfills missing official India files during pipeline runs. | It only warms a small batch per run and does not yet complete the full India lane by itself. |
| `pipeline/universe/sources.py` | Already fetches `Nifty 500` and `Nifty 50` from NSE. | It does not yet persist the extra identifier bridge needed for stronger NSE/BSE fallback. |
| `api/routers/stocks.py` | India stock detail pages already work through the shared response model. | Forecasts, peers, events, and stock-news tabs still use shared `FMP`-backed live enrichment logic and need India-specific replacements or clearer disabling. |
| `frontend/src/lib/api.ts` | The adapter layer already lets India screens consume normalized backend data without source-specific UI logic. | It will benefit automatically once richer official India data is available. |
| `tests/test_providers.py` | Covers the official India provider, import flow assumptions, and shared provider routing. | More India-specific regression cases are still useful once BSE and event ingestion land. |
| `tests/test_scheduler.py` | Covers the official India warmup candidate logic in the scheduler. | More end-to-end India coverage is still needed after the lane grows beyond the current slice. |

## What We Have Completed

- Built an official India file-backed fundamentals provider.
- Added canonical storage under `data/official_india/`.
- Added importer support for downloaded `NSE` and `BSE` files.
- Added live `NSE` fetch for quarterly financial-result detail rows and shareholding rows.
- Added official-first routing for India fundamentals in the provider registry.
- Added local ratio computation so missing source fields do not block scoring.
- Added scheduler warmup support for the starter India basket and broader gradual rollout.

## What Is Left

The major remaining gaps are:

- No live automatic `BSE` fetch client yet.
- India latest quotes and daily historical prices still rely mainly on `yfinance`.
- India announcements, board meetings, and corporate actions are not yet ingested from official exchange endpoints.
- India order-book depth, delivery percentage, bulk/block deals, derivatives, insider disclosures, and structured disclosure parsing are not yet part of the India lane.
- The DB does not yet carry a full India identifier bridge such as `isin`, `nse_symbol`, `bse_symbol`, and `bse_scripcode`.
- The current official fetch slice focuses on financial-result rows and shareholding; full balance-sheet, cash-flow, and richer statement extraction are still incomplete.
- Raw payload preservation, source auditing, and stronger validation rules are still limited.
- Some India stock-detail tabs still pass through shared `FMP` enrichment logic and need India-aware handling.

## Required India Data Stack

These are the India-market datasets we should explicitly treat as required, not optional nice-to-haves.

### 1. Core market data baseline layer

From `NSE` and `BSE` we should capture:

- `LTP`
- `Open / High / Low / Close`
- volume
- `VWAP`
- delivery percentage

Why it matters:

- trend detection,
- accumulation vs distribution,
- price-move validation,
- execution-quality checks.

Delivery percentage is especially important in India because it helps separate real positional buying from purely churn-heavy trading activity.

### 2. Order flow signals

From exchange quote/depth surfaces we should capture:

- bid / ask depth,
- top-5 market depth,
- intraday volume spikes.

Why it matters:

- shows where liquidity is actually sitting,
- helps detect liquidity traps and fake breakouts,
- gives a better read of real money movement than price alone.

For this product, these signals are especially valuable as execution and breakout-validation overlays, even if they are not the first scoring inputs.

### 3. Corporate events

From both exchanges we should ingest:

- corporate announcements,
- board meetings,
- corporate actions.

Why it matters:

- announcements can move price immediately,
- board meetings set up volatility around results,
- corporate actions are required for long-term price adjustment and event context.

### 4. Bulk deals and block deals

This should be treated as a high-signal dataset.

Needed data:

- bulk deals,
- block deals,
- buyer / seller identity where published,
- traded quantity and price.

Why it matters:

- shows institutional or concentrated money movement,
- often gives early conviction signals before price fully reacts,
- is one of the strongest ownership-flow datasets available in India.

### 5. Shareholding patterns

Needed fields:

- promoter holding,
- `FII`,
- `DII`,
- public shareholding,
- promoter pledge where available.

Why it matters:

- long-term conviction analysis,
- ownership-quality analysis,
- trend confirmation beyond price action.

### 6. Index-level and sector-level data

Needed data:

- `NIFTY`,
- `SENSEX`,
- sector indices such as `IT`, `BANK`, `FMCG`, and other major sector baskets.

Why it matters:

- most stock movement is partly driven by index and sector context,
- sector-relative strength is often more important than standalone stock movement,
- stock analysis is incomplete without market and sector regime context.

### 7. Derivatives data

From `NSE` derivatives surfaces we should ingest:

- open interest,
- change in open interest,
- put / call ratio,
- max pain,
- option chain structure.

Why it matters:

- helps read sentiment,
- improves support/resistance mapping,
- helps explain expiry-week and event-driven moves.

This is a key professional layer for India because many important short-term positioning signals show up in `F&O` before they fully show up in cash-market price action.

### 8. Company disclosures

Needed disclosure inputs:

- quarterly results PDFs,
- investor presentations,
- concall transcripts when available.

Why it matters:

- structured API fields never carry the full story,
- these disclosures contain management guidance, capex plans, risk commentary, and strategic changes,
- very few systems structure this well, so the upside from parsing it is high.

### 9. Insider trading disclosures

Needed data:

- promoter buying,
- promoter selling,
- insider trade disclosures.

Why it matters:

- insider buying often signals confidence,
- insider selling can be an early caution flag,
- it adds a behavior-based signal layer that pure fundamentals miss.

### 10. Market-wide indicators

Needed data:

- advance / decline ratio,
- market breadth,
- `India VIX`.

Why it matters:

- helps measure panic vs greed,
- gives a better regime view than index price alone,
- improves timing discipline around risk-on and risk-off environments.

## Improvements Required First

These are the highest-priority improvements if the goal is trustworthy India data for investment decisions.

### 1. Improve data correctness before adding more scoring logic

- Persist `isin`, `nse_symbol`, `bse_symbol`, and `bse_scripcode` in the stock master.
- Add a hardened India HTTP client with cookie priming, retries, throttling, and response validation.
- Save both raw payloads and normalized payloads with source, fetch timestamp, and endpoint metadata.
- Add live `BSE` fetch support so `NSE -> BSE -> Yahoo` becomes real runtime behavior instead of mostly planned behavior.
- Add stale-data detection, duplicate-quarter detection, and unit normalization checks for lakh/crore/absolute-value mismatches.
- Reconcile key fields across `NSE`, `BSE`, and `Yahoo` before storing suspicious outliers.

### 2. Reduce India price dependency on Yahoo

- Ingest official exchange archives or bhavcopy-style datasets for daily OHLCV.
- Add source-tagged latest quote logic from `NSE` and `BSE`.
- Include `LTP`, `VWAP`, and delivery percentage in the canonical India price layer.
- Add top-level quote/depth support for bid/ask and top-5 market depth where available.
- Adjust local price history for splits, bonuses, and major corporate actions.
- Keep `Yahoo` only as the fallback when official lanes are blocked or incomplete.

### 3. Add official disclosure/event ingestion

- Ingest corporate announcements from `NSE`.
- Add `BSE` announcement fallback using `scripcode`.
- Ingest board meetings, dividend announcements, splits, bonuses, rights issues, and other corporate actions.
- Ingest bulk deals, block deals, and insider-trading disclosures as separate structured feeds.
- Parse quarterly results PDFs, investor presentations, and concall transcripts into a research-friendly format.
- Use this to power the India event surface and disclosure feed instead of relying on vendor-style stock news.

### 4. Build the India market-structure and derivatives layer

- Ingest `NIFTY`, `SENSEX`, and sector-index series as explicit India context inputs.
- Add advance/decline ratio, breadth, and `India VIX` as regime indicators.
- Ingest `F&O` data including `OI`, change in `OI`, `PCR`, max pain, and option-chain structure.
- Use these as sentiment, support/resistance, and execution overlays instead of treating them as optional extras.

## Factors To Add For Better Indian Market Analysis

These additions would improve investing usefulness after the data foundation is stronger.

### Ownership and governance factors

- Promoter holding trend over time.
- Promoter pledge percentage and pledge trend.
- `FII`, `DII`, and public-shareholding trend.
- Insider/promoter buy-sell disclosures.
- Auditor resignation, qualified audit opinion, delayed filings, and governance red flags.

### Business-quality and capital-allocation factors

- Cash conversion cycle, debtor days, inventory days, and working-capital intensity.
- `ROCE` trend versus capex and reinvestment trend.
- `FCF` conversion from reported profit.
- Dilution history and capital-raising frequency.
- Dividend consistency and payout sustainability for India-specific dividend names.

### Sector-specific India factors

- Banks and `NBFCs`: `GNPA`, `NNPA`, `PCR`, `CASA`, `NIM`, credit cost, and capital adequacy.
- Industrials and infra: order-book to revenue ratio, execution growth, and receivable intensity.
- Commodity businesses: leverage, realization trend, and inventory-cycle sensitivity.
- Exporters such as `IT` and pharma: `USD/INR` sensitivity and revenue mix exposure.
- Rate-sensitive sectors: home finance, autos, real estate, and capital goods sensitivity to RBI and bond-yield moves.

### Investability and market-structure factors

- Free-float adjusted market cap.
- Delivery percentage and traded-value quality.
- `ASM/GSM` lists, surveillance actions, and `F&O` ban status.
- Bid/ask depth imbalance and market-depth concentration.
- Bulk/block-deal follow-through.
- `OI`, `PCR`, max pain, and option-chain-derived support/resistance.
- Listing-age quality plus disclosure consistency.
- Event-risk flags for results, dividends, and board meetings.

## How To Get The Data More Correct

If the objective is “good enough to invest from”, these safeguards matter more than adding extra scores too early:

- Prefer official filings over summary vendor fields whenever there is a conflict.
- Keep source tags on every important India field.
- Reject or quarantine rows with impossible jumps in revenue, debt, shareholding, or ratios until rechecked.
- Reconcile cash-market price, delivery percentage, bulk/block deals, and derivatives data against the same trade date so signals are not mixed across stale sessions.
- Store whether each row is `standalone` or `consolidated` and do not mix them silently.
- Preserve raw disclosure payloads so normalization bugs can be audited later.
- Add tests for quarter matching, promoter-history parsing, ratio derivation, price normalization, disclosure parsing, derivatives mapping, and `BSE` fallback mapping.

## Suggested Execution Order

1. Finish identifier mapping and resilient `NSE/BSE` fetch infrastructure.
2. Finish official India core market data: `LTP`, `OHLC`, volume, `VWAP`, delivery percentage, and adjusted price history.
3. Add announcements, board meetings, corporate actions, bulk/block deals, insider disclosures, and disclosure parsing into DB and API surfaces.
4. Add index, sector, breadth, and derivatives layers for regime and sentiment context.
5. Remove remaining India dependence on shared `FMP` detail-tab enrichment.
6. Add governance, ownership, and sector-specific India factors on top of the cleaner dataset.

## Bottom Line

Completed today:

- official India fundamentals lane,
- local canonical storage,
- live `NSE` financial/shareholding fetch,
- local ratio computation,
- scheduler-assisted warmup.

Still left:

- live `BSE`,
- official India prices and delivery-based market data,
- official disclosures/events/deals/insider feeds,
- derivatives, breadth, and sector-index context,
- stronger identifiers and audit trails,
- India-specific replacements for shared vendor-only detail enrichments.

The best next move is not adding more ranking formulas first.
The best next move is improving source quality, identifier quality, price correctness, delivery/depth visibility, and official disclosure coverage so the analysis becomes trustworthy enough for real investing.

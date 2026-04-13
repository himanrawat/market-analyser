# India Market — Unimplemented Gap List

Date: April 13, 2026

This document consolidates everything that is **not yet implemented** for the Indian market
across all existing docs. It is the single checklist to work from.

Sources cross-referenced:
- `INDIA_DATA_LANE_IMPLEMENTATION.md` — target architecture reference
- `INDIA_MARKET_IMPROVEMENT_PLAN.md` — priority and dataset requirements
- `MARKET_LANE_REFACTOR_SUMMARY.md` — post-refactor remaining gaps (most recent)
- `IMPLEMENTATION_STATUS.md` — overall phase status

---

## Already Completed (do not re-implement)

- Official India fundamentals lane backed by on-disk `data/official_india/` files
- Live NSE fetch for quarterly P&L financial-result rows and shareholding rows
- India-first routing in `registry.py` (NSE official → yfinance fallback)
- Local ratio computation: ROE, ROCE, debt/equity, margins, P/E, P/B, FCF, EV/EBITDA
- Scheduler warmup for starter basket and gradual Nifty 500 rollout
- NSE runtime endpoints in `india_market_provider.py`:
  - `quote-equity` (latest quote)
  - `corporate-announcements` (India stock news)
  - `corporate-board-meetings` (India events)
  - `corporate-actions` (India events)
- Stock master identifier columns: `isin`, `nse_symbol`, `bse_symbol`, `bse_scripcode`
- NSE equity metadata / profile enrichment
- India stock detail separated from FMP entirely

---

## Gap 1 — Live BSE Fetch Client

**What is missing:**
BSE exists only as a file-import fallback format. There is no automatic live HTTP client
that fetches from BSE endpoints at runtime.

**BSE endpoints that need a live client:**
- `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` — corporate announcements
- `https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?scripcode=` — corporate actions
- `https://api.bseindia.com/BseIndiaAPI/api/BoardMeeting/w?scripcode=` — board meetings
- `https://api.bseindia.com/BseIndiaAPI/api/StockReachGraph/w?scripcode=` — price/graph fallback

**Why it blocks other gaps:**
The `NSE → BSE → Yahoo` fallback chain is partially planned but mostly paper logic.
BSE is the required fallback for announcements, events, and price when NSE fails or returns empty.
BSE endpoints key by `bse_scripcode`, which is now persisted in the stock master — the identifier
bridge is ready, the client is not.

---

## Gap 2 — Official India Daily Historical Price History

**What is missing:**
Daily OHLCV history is still sourced entirely from yfinance. No official bhavcopy-style
or NSE/BSE archive ingestion exists.

**Specifically missing:**
- NSE bhavcopy / archive daily OHLCV ingestion
- BSE bhavcopy equivalent as fallback
- Corporate-action-adjusted historical price series (splits, bonuses, rights)
- Backfill pipeline for 3-year history on first run
- Incremental daily refresh from official archives

**Why it matters:**
yfinance adjusted prices are not always consistent with Indian corporate actions.
Delivery percentage — which is one of the highest-signal India-specific fields — is only
available from official exchange archives, not yfinance.

---

## Gap 3 — VWAP and Delivery Percentage in the Quote Layer

**What is missing:**
The current NSE quote-equity endpoint is fetched, but the canonical quote layer
does not yet extract or persist:
- `VWAP`
- delivery percentage
- delivery volume

**Why it matters:**
Delivery percentage separates real positional buying from churn-heavy trading.
It is one of the strongest India-specific conviction filters and is not available
from any vendor fallback.

---

## Gap 4 — Order Flow and Market Depth

**What is missing:**
- Bid/ask depth snapshots
- Top-5 market depth
- Intraday volume spike overlays
- Source-tagged, timestamped microstructure data

**Target source:**
NSE quote/depth endpoints first, BSE depth surfaces as fallback.
Empty result rather than fabricating data if no official source exists.

**Why it matters:**
Needed for execution-quality checks, fake-breakout detection, and liquidity-trap
detection. Also confirms whether institutional-style size is sitting near key
price levels before entering a position.

---

## Gap 5 — Bulk Deals and Block Deals

**What is missing:**
- NSE bulk deal disclosures
- BSE bulk deal disclosures
- Block deal feed
- Buyer/seller identity where published
- Traded quantity and price

**Why it matters:**
Bulk and block deals are the highest-signal institutional ownership-flow dataset
available in India. They often show concentrated money movement before price fully reacts.
This is described in the plan as a priority dataset, not optional.

---

## Gap 6 — Insider Trading Disclosures

**What is missing:**
- Promoter buying records
- Promoter selling records
- Insider trade disclosures from NSE and BSE

**Why it matters:**
Insider buying is a behavior-based confidence signal. Insider selling can be an
early caution flag. Pure fundamentals miss this layer entirely.

---

## Gap 7 — Corporate Disclosure Parsing

**What is missing:**
- Quarterly results PDF ingestion and metadata extraction
- Investor presentation ingestion
- Concall transcript references where available
- Parsed qualitative fields: guidance, capex commentary, management signals

**Why it matters:**
Structured API fields never carry the full story. These disclosures contain information
that summary APIs do not expose. The plan explicitly calls this out as high-upside
because few systems structure it well.

---

## Gap 8 — India Index, Breadth, and Sector-Index Layer

**What is missing:**
- NIFTY and SENSEX series as explicit structured India context inputs
- Sector indices: BANK, IT, FMCG, and other major baskets
- Advance/decline ratio
- Market breadth
- India VIX as a structured ingestion (note: India VIX exists as a macro snapshot field
  but is not yet ingested as a time series from an official exchange source)

**Why it matters:**
Most stock movement is partly driven by index and sector context, not stock-specific
signals alone. Sector-relative strength is often more important than standalone stock
movement. Stock analysis is incomplete without market and sector regime context.

---

## Gap 9 — Derivatives Layer (F&O)

**What is missing:**
- Open interest (OI)
- Change in OI
- Put/call ratio (PCR)
- Max pain
- Option chain structure

**Target source:** NSE derivatives endpoints.

**Why it matters:**
Many important short-term positioning signals in India show up in F&O before they
fully appear in cash-market price action. This is a key professional-grade layer
for the India market that has no equivalent in the US lane.

---

## Gap 10 — Full Financial Statement Extraction

**What is missing:**
The live NSE fetch currently pulls quarterly P&L rows only. Missing:
- Balance sheet rows (assets, liabilities, working capital)
- Cash flow statement rows
- Full XBRL/structured statement extraction where available

**Why it matters:**
Many important ratios — cash conversion cycle, debtor days, inventory days, working
capital intensity, FCF conversion — require balance sheet and cash flow data.
Local ratio computation is currently limited by the incompleteness of the imported rows.

---

## Gap 11 — Data Quality and Audit Infrastructure

**What is missing:**
- Raw payload preservation with source, fetch timestamp, and endpoint metadata for every India fetch
- Stale-data detection
- Duplicate-quarter detection
- Unit normalization checks (lakh vs crore vs absolute-value mismatches from different sources)
- Cross-source reconciliation before storing suspicious outliers
- Standalone vs consolidated tracking — rows are not yet tagged, so mixing is silent
- Structured source tags on every important India field in the DB

**Why it matters:**
Without these safeguards the data is not trustworthy enough for real investing decisions.
The plan explicitly states that improving source quality matters more than adding more
scoring formulas.

---

## Gap 12 — India Governance and Ownership Factors

**What is missing (scoring/analysis layer):**
- Promoter pledge percentage and pledge trend
- FII, DII, and public shareholding trend over time (current shareholding is single-snapshot)
- Auditor resignation flag
- Qualified audit opinion flag
- Delayed filings flag
- General governance red-flag detection

**Why it matters:**
Promoter pledge and governance signals are India-specific risk factors that do not exist
in the US scoring model. Adding them requires the official shareholding and disclosure
pipeline to be stable first.

---

## Gap 13 — Sector-Specific India Scoring Factors

**What is missing:**
These sector-specific fundamental factors are not yet computed or stored:

- **Banks and NBFCs:** GNPA, NNPA, PCR (provision coverage), CASA ratio, NIM, credit cost, capital adequacy ratio
- **Industrials and infra:** order-book to revenue ratio, execution growth, receivable intensity
- **Commodity businesses:** realization trend, inventory-cycle sensitivity
- **Exporters (IT, pharma):** USD/INR sensitivity, revenue mix exposure (domestic vs export)
- **Rate-sensitive sectors:** sensitivity scoring for home finance, autos, real estate, capital goods

**Why it matters:**
A generic scoring formula applied uniformly across all India sectors will produce wrong rankings.
A bank scored on P/E vs a commodity company on the same formula is apples-to-oranges.

---

## Gap 14 — Investability and Market-Structure Flags

**What is missing:**
- Free-float adjusted market cap
- ASM (Additional Surveillance Measure) list status
- GSM (Graded Surveillance Measure) list status
- F&O ban status
- Listing-age quality score
- Disclosure consistency score
- Event-risk flag (upcoming results, dividend, board meeting within N days)

**Why it matters:**
A stock on the ASM/GSM list or in F&O ban is not safely investable regardless of fundamentals score.
These are hard filters, not soft scoring inputs. Missing them means the ranked list can surface
stocks that cannot or should not be acted on.

---

## Gap 15 — India Forecasts and Peer Mapping

**What is missing:**
- India-appropriate analyst forecast lane (EPS estimates, target prices, recommendation consensus)
- India peer comparison logic beyond same-sector local ranking

**Current state:**
India forecasts are intentionally disabled with an explicit note in `api/routers/stocks.py`.
No FMP usage for India is correct. But there is no replacement source defined yet.

**Note:**
This is lower priority than the data quality and price gaps above. The plan calls this out
as a future lane, not an immediate blocker.

---

## Execution Order (from the plan)

1. **Finish data quality and audit infrastructure** — raw payload preservation, source tags,
   unit normalization, standalone/consolidated tracking. No new data adds value without this.
2. **Live BSE client** — completes the NSE → BSE fallback chain.
3. **Official India prices** — bhavcopy/archive OHLCV, VWAP, delivery percentage, adjusted history.
4. **Announcements, board meetings, corporate actions** — NSE already partially done; BSE fallback
   and full normalization still needed.
5. **Bulk/block deals and insider disclosures** — high-signal datasets, implement after events.
6. **Full financial statement extraction** — balance sheet and cash flow rows to unblock ratio depth.
7. **Index, breadth, sector-index, India VIX time series** — regime and sector context layer.
8. **Derivatives (F&O)** — OI, PCR, max pain, option chain.
9. **Order flow and market depth** — bid/ask depth, top-5 depth, volume spikes.
10. **Disclosure parsing** — PDFs, concall transcripts, investor presentations.
11. **Governance/ownership factors** — pledge trend, audit flags, FII/DII trend.
12. **Sector-specific scoring** — GNPA/NIM for banks, order book for industrials, etc.
13. **Investability flags** — ASM/GSM/F&O ban, free-float market cap, event-risk flags.
14. **India forecasts/peers** — requires a new India-appropriate data source.

# India Data Lane Implementation

This document defines the implementation plan for the India market-data lane after removing Financial Modeling Prep from India-specific logic.

Scope:
- India-only data acquisition and normalization
- NSE-first and BSE-second sourcing strategy
- Yahoo Finance as the last-resort fallback for India
- reliability requirements for undocumented public endpoints
- code-organization guidance for the current repository

Out of scope:
- removing FMP from the US lane
- redesigning the full provider abstraction for every market in one pass
- frontend redesign

Execution priority note:
- US market enhancement work is on hold
- the immediate focus is to complete the Indian market implementation first

## Goal

For Indian stocks, the system should prefer official and exchange-published data over vendor APIs:

1. NSE public APIs / public filings
2. BSE public APIs / public filings
3. Yahoo Finance only if both official lanes fail or do not expose the required field

FMP should no longer be considered part of the India runtime path because the Starter plan does not provide dependable India coverage for the required features.

## Why This Change

The current repo already moved part of the India fundamentals path toward official sources, but the migration is incomplete:

- Official India fundamentals are already read from local NSE/BSE files by `IndiaOfficialFundamentalsProvider`.
- Live NSE fetch exists for quarterly financial-result rows and shareholding rows.
- BSE exists today only as an import/read fallback format, not as a live automatic fetch client.
- India prices and profile-like metadata still depend on Yahoo Finance.
- FMP still exists in the broader app for US fundamentals, peers, analyst forecasts, events, and stock-specific news.

The target state for India is:

- official exchange data as the source of truth
- local canonical storage of normalized India payloads
- Yahoo Finance only as the emergency fallback

## Current Codebase State

Relevant files in the current workspace:

- `pipeline/providers/india_official_provider.py`
  Reads normalized India files from `data/official_india/`.
- `pipeline/importers/india_official.py`
  Imports NSE/BSE files and currently supports live NSE fetching.
- `pipeline/providers/registry.py`
  Routes India fundamentals to official files first, then Yahoo fallback.
- `pipeline/providers/yfinance_provider.py`
  Still serves India prices and fallback fundamentals/profile.
- `pipeline/scheduler.py`
  Warms the India official lane gradually, then syncs the market data.

Important current limitations:

- Live automatic fetching is implemented for NSE, not BSE.
- The scheduler only warms a small batch of India names per run.
- The database schema does not currently persist the identifiers needed for a strong NSE/BSE bridge, such as `isin`, `nse_symbol`, and `bse_scripcode`.
- India events/announcements/board meetings are not yet sourced from official exchange APIs.

## Data Source Strategy

### Fundamentals and Shareholding

Primary objective:
- use official exchange-published financial-result and shareholding data
- normalize it into the existing `FundamentalSnapshot` shape
- compute ratios locally where the source does not provide them

Priority order:

1. NSE filings and APIs
2. BSE filings and APIs
3. Yahoo Finance fallback only if both are unavailable or incomplete

### Prices

Target objective:
- reduce India dependence on Yahoo for daily and latest price data

Priority order:

1. NSE official market endpoints and archives
2. BSE official market endpoints and archives
3. Yahoo Finance fallback

Note:
- The provided NSE and BSE endpoints are useful for quote and event-style surfaces.
- For durable daily OHLCV history, exchange archives or bhavcopy-style datasets will likely be more reliable than ad hoc quote endpoints alone.

Required India baseline market-data fields:

- `LTP`
- `Open / High / Low / Close`
- volume
- `VWAP`
- delivery percentage

Why they matter:

- trend detection
- accumulation vs distribution analysis
- stronger validation of whether price moves are backed by real delivery activity

### Order Flow Signals

Target objective:
- capture the microstructure layer that shows where liquidity and real money are sitting

Priority order:

1. NSE quote/depth surfaces
2. BSE quote/depth surfaces
3. empty result rather than inventing a weak fallback

Desired fields:

- bid / ask depth
- top-5 market depth
- intraday volume spikes

Use cases:

- execution-quality checks
- fake-breakout detection
- liquidity-trap detection
- identifying whether institutional-style size is sitting near key price levels

Important note:
- for this product, order-flow data is best treated as an execution and confirmation overlay, not a replacement for the slower monthly investment framework

### Corporate Disclosures and Events

For India-specific event intelligence, the official lane should ingest:

- corporate announcements
- board meetings
- corporate actions
- bulk deals
- block deals
- insider-trading disclosures

This data should populate the existing event/news-like surfaces where appropriate, with clear source tagging.

### Index, Sector, and Breadth Layer

For India-specific macro and market-context signals, the lane should ingest:

- `NIFTY`
- `SENSEX`
- sector indices such as `BANK`, `IT`, `FMCG`, and other major market sectors
- advance / decline ratio
- market breadth
- `India VIX`

This matters because a large share of stock movement is driven by index and sector context rather than stock-specific news alone.

### Derivatives Layer

For India-specific sentiment and support/resistance context, the lane should ingest:

- open interest (`OI`)
- change in `OI`
- put / call ratio (`PCR`)
- max pain
- option-chain structure

Use cases:

- market sentiment
- support/resistance mapping
- expiry-week behavior
- confirming whether moves are being supported by derivatives positioning

### Company Disclosures

The lane should eventually capture and preserve:

- quarterly results PDFs
- investor presentations
- concall transcripts where available

Important note:
- these are messy and often require PDF or document parsing
- they are still valuable because they contain guidance, capex commentary, and management signals that summary APIs do not expose

### Profile and Security Master Data

The app currently uses Yahoo for some profile fields such as:

- market cap
- listing date
- company description
- sector / industry completion

The long-term India target should move as much of this as practical to exchange metadata, with Yahoo retained only as a missing-field fallback.

## NSE Endpoints To Support

### Existing NSE endpoints already aligned with the current repo

These are already partially represented by the live NSE importer:

- `https://www.nseindia.com/api/equity-meta-info?symbol=RELIANCE`
- `https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol=RELIANCE&period=Quarterly`
- `https://www.nseindia.com/api/corporates-financial-results-data`
- `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=RELIANCE`

### Additional NSE endpoints requested for implementation

1. Corporate announcements

- `https://www.nseindia.com/api/corporate-announcements?index=equities`
- expected useful fields:
  - company name
  - subject
  - description
  - date
  - attachment / PDF link

2. Board meetings

- `https://www.nseindia.com/api/corporate-board-meetings?index=equities`

3. Corporate actions

- `https://www.nseindia.com/api/corporate-actions?index=equities`

4. Quote-equity endpoint

- `https://www.nseindia.com/api/quote-equity?symbol=RELIANCE`

Use cases:
- latest quote or quote-like metadata
- market-cap-related metadata if exposed
- exchange security metadata
- validation of active symbol state

5. Market depth and order book surfaces

- if NSE exposes usable quote-depth payloads through quote endpoints, they should be captured for:
  - bid / ask depth
  - top-5 market depth
  - execution-quality overlays

6. Market-wide breadth and derivatives surfaces

- `India VIX`
- advance / decline style breadth where available
- option-chain and derivatives endpoints for `OI`, `PCR`, and related sentiment context

## BSE Endpoints To Support

1. Corporate announcements

- `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=Company%20Update`

2. Corporate actions

- `https://api.bseindia.com/BseIndiaAPI/api/CorporateAction/w?scripcode=500325`

3. Board meetings

- `https://api.bseindia.com/BseIndiaAPI/api/BoardMeeting/w?scripcode=500325`

4. Price/graph endpoint

- `https://api.bseindia.com/BseIndiaAPI/api/StockReachGraph/w?scripcode=500325`

Use cases:
- latest / historical graph-derived pricing where usable
- fallback when NSE quote or market endpoints fail

5. Deal, disclosure, and event surfaces

- BSE should be used as fallback where it exposes:
  - announcements
  - board meetings
  - corporate actions
  - deal and disclosure metadata

6. Quote/depth-style surfaces

- if BSE exposes usable quote/depth payloads, they should be used for:
  - latest quote fallback
  - market-depth fallback
  - execution overlays

## Mandatory Request Behavior

### NSE request rules

NSE must be treated as a browser-protected public endpoint, not a stable developer API.

Minimum headers:

```http
User-Agent: Mozilla/5.0
Accept: application/json
Referer: https://www.nseindia.com/
Connection: keep-alive
```

Cookie handling requirement:

1. First hit the homepage:
   - `https://www.nseindia.com/`
2. Store and reuse the returned cookies in the session
3. Then call the NSE API endpoint

If cookie priming is skipped, `403` errors should be expected.

### Reliability constraints for both NSE and BSE

The implementation must assume:

- random `403` responses
- undocumented response changes
- rate limits
- intermittent non-JSON payloads
- empty payloads for valid instruments
- fields appearing and disappearing over time

## Required Reliability Design

The India lane should be built around a resilient HTTP client with these behaviors:

### Session management

- one reusable session object per provider client
- cookie jar persistence during a run
- NSE session priming before protected API calls
- ability to re-prime cookies after `403`

### Rate limiting

- conservative per-host throttling
- request jitter
- bounded concurrency
- backoff after `403`, `429`, or repeated empty responses

### Retry policy

Recommended policy:

- retry only on transient failures
- do not retry indefinitely
- distinguish:
  - blocked
  - malformed response
  - no data
  - symbol mapping failure

### Raw payload preservation

For every official India fetch, store:

- raw payload snapshot
- normalized payload
- fetch timestamp
- source endpoint
- source market (`nse` or `bse`)

This makes debugging schema drift and correctness issues much easier.

### Defensive normalization

Normalizers should:

- treat field names as unstable
- accept alternate date formats
- accept mixed numeric and string values
- tolerate missing fields
- avoid failing the full stock if one subsection is malformed

## Canonical Data Model Requirements

For strong NSE/BSE fallback, the stock master should eventually carry exchange identifiers, not only ticker text.

Recommended identifiers to persist:

- `isin`
- `nse_symbol`
- `bse_symbol` if available
- `bse_scripcode`
- optional exchange name / listing venue flags

Why this matters:

- NSE and BSE do not always key data the same way
- BSE endpoints commonly expect `scripcode`
- without an identifier bridge, BSE fallback remains heuristic and brittle

## Target Feature Mapping

### India fundamentals

Desired path:

1. NSE official filings and results APIs
2. BSE official filings and results APIs
3. Yahoo Finance fallback

Expected output:

- quarterly rows in canonical local JSON
- DB fundamentals populated from canonical data
- local ratio computation for missing valuation or return fields

### India shareholding

Desired path:

1. NSE official shareholding
2. BSE equivalent disclosure if available
3. no Yahoo dependency unless a truly minimal fallback is required

Expected output:

- promoter holding history
- shareholding timeline suitable for latest snapshot and trend use

### India latest quote

Desired path:

1. NSE quote and/or official market endpoints
2. BSE quote/graph endpoint
3. Yahoo Finance fallback

Expected output:

- latest close / traded price approximation for refresh surfaces
- source-tagged quote freshness
- `LTP`
- `VWAP`
- delivery percentage where available

### India daily historical price history

Desired path:

1. NSE archive / official historical source
2. BSE archive / official historical source
3. Yahoo Finance fallback

Expected output:

- daily OHLCV bars
- stable ingestion for backfill and incremental refresh
- corporate-action-adjusted history where possible

### India order flow and market depth

Desired path:

1. NSE depth / quote surfaces
2. BSE depth / quote surfaces
3. empty result if no trustworthy official depth source exists

Expected output:

- bid / ask depth snapshots
- top-5 market depth
- execution and breakout-validation overlays
- date/time-stamped source-tagged microstructure data

### India announcements, board meetings, and corporate actions

Desired path:

1. NSE official endpoints
2. BSE official endpoints
3. no FMP dependency

Expected output:

- normalized event records
- optionally attachment URLs for filings
- headline/subject extraction for qualitative review

### India bulk deals and block deals

Desired path:

1. NSE official deal disclosures
2. BSE official deal disclosures
3. empty result rather than weak vendor substitution

Expected output:

- buyer / seller identity where published
- traded quantity and trade price
- a structured ownership-flow feed usable for conviction analysis

### India company disclosures

Desired path:

1. NSE filing/disclosure surfaces
2. BSE filing/disclosure surfaces
3. raw document preservation for later parsing

Expected output:

- quarterly results PDFs
- investor presentations
- concall transcript references where available
- parsed metadata for qualitative review

### India insider trading disclosures

Desired path:

1. NSE official insider-trade disclosures
2. BSE official insider-trade disclosures
3. empty result rather than noisy fallback

Expected output:

- promoter buying / selling records
- insider-trade history
- confidence / caution overlays for research review

### India index, breadth, and derivatives context

Desired path:

1. NSE and BSE index surfaces
2. NSE derivatives surfaces
3. Yahoo only for emergency fallback on the broadest index history if needed

Expected output:

- `NIFTY`, `SENSEX`, and sector-index context
- advance / decline ratio
- market breadth
- `India VIX`
- `OI`, change in `OI`, `PCR`, max pain, and option-chain context

### India stock-specific news

Important caveat:

- exchange announcement feeds are not the same thing as editorial news

Reasonable product decision:

- treat official announcements as the India “stock disclosure feed”
- keep general market news separate
- do not promise a vendor-style India news feed unless a dedicated news source is added later

## Fallback Rules

Recommended India fallback rules by data type:

- Fundamentals:
  - NSE
  - BSE
  - Yahoo

- Shareholding:
  - NSE
  - BSE
  - optional empty result before Yahoo if Yahoo quality is poor

- Latest quote:
  - NSE
  - BSE
  - Yahoo

- Historical prices:
  - NSE archive
  - BSE archive
  - Yahoo

- Announcements / board meetings / corporate actions:
  - NSE
  - BSE
  - empty result rather than Yahoo, unless Yahoo adds real value for the exact event type

## Recommended Implementation Phases

### Phase 1: India identifier foundation

Add and populate the identifiers needed for reliable official-source routing:

- `isin`
- `nse_symbol`
- `bse_scripcode`

This should be treated as foundational, because BSE fallback quality depends on it.

### Phase 2: Harden the official India HTTP layer

Build a reusable India market client that handles:

- session priming
- cookies
- required headers
- throttling
- retries
- raw response capture

### Phase 3: Complete fundamentals and shareholding lane

Use official data to populate:

- quarterly fundamentals
- promoter holding / shareholding
- locally computed ratios

Yahoo remains only the final fallback.

### Phase 4: Add disclosure/event ingestion

Normalize:

- corporate announcements
- board meetings
- corporate actions
- bulk deals
- block deals
- insider-trading disclosures
- disclosure metadata such as result PDFs and investor presentations

Then map these into the DB event and disclosure surfaces.

### Phase 5: Reduce Yahoo dependency for India prices and baseline market data

Implement official-source India pricing where feasible.

Yahoo should remain available only as:

- emergency fallback
- gap filler during official-source outages

This phase should also include:

- `LTP`
- `OHLC`
- volume
- `VWAP`
- delivery percentage
- corporate-action-adjusted history

### Phase 6: Add order flow, breadth, and derivatives context

Implement the India-specific market-structure layer:

- bid / ask depth
- top-5 market depth
- volume-spike overlays
- `NIFTY` / `SENSEX` / sector-index context
- advance / decline ratio and market breadth
- `India VIX`
- `OI`, change in `OI`, `PCR`, max pain, and option-chain context

### Phase 7: Remove FMP from India code paths entirely

Once India routes are stable:

- remove any India-specific FMP branches
- remove India-specific FMP assumptions from docs, tests, and health checks

## Code Organization Recommendation

The repo should not collapse everything shared into one country file. The cleaner structure is:

- shared provider infrastructure remains shared
- country-specific market logic moves into country-specific modules

Recommended direction:

- `pipeline/providers/india_market.py` or `pipeline/providers/india_market/`
- `pipeline/providers/us_market.py` or `pipeline/providers/us_market/`
- shared:
  - `registry.py`
  - `dto.py`
  - `errors.py`
  - `cache.py`
  - `_http.py`
  - Yahoo client if still shared across both markets

For India specifically, the best consolidation opportunity is to unify the logic currently split across:

- `pipeline/importers/india_official.py`
- `pipeline/providers/india_official_provider.py`

Why these are good merge candidates:

- both operate on the same canonical `data/official_india/` layout
- both are India-specific
- one fetches/writes official payloads, the other reads/parses them
- they already form one conceptual subsystem

Recommended India package boundaries:

- HTTP client and cookie/session handling
- raw/normalized payload persistence
- symbol and identifier mapping
- fundamentals/shareholding normalization
- announcements/actions/board meetings normalization
- provider facade used by `registry.py`

## Product Impact If This Plan Is Followed

Expected positive effects:

- India lane becomes cheaper and closer to the official source of truth
- fewer false gaps from FMP plan limits
- better alignment with the PRD hybrid India direction
- easier auditing because filings and official payloads are stored locally

Expected tradeoffs:

- more implementation work around cookies and anti-bot behavior
- more schema-drift maintenance than a stable paid API
- BSE fallback requires identifier mapping work
- official announcements are not a drop-in replacement for vendor editorial news

## Acceptance Criteria

The India implementation can be considered successful when:

- India fundamentals no longer use FMP anywhere in runtime routing
- India shareholding no longer depends on vendor summary fields
- India official fetch works with cookie priming and retry logic
- NSE failures fall back to BSE where supported
- Yahoo is used only as the documented last resort
- normalized official India data is stored locally and auditable
- India baseline market data includes official quote/history coverage plus delivery-aware fields where available
- India event/disclosure coverage includes announcements, corporate actions, deals, and insider-trade feeds
- India market context includes breadth, sector/index, and derivatives overlays
- scheduler runs can complete India sync without FMP plan-limit behavior

## Notes For This Repository

This document is based on the current workspace state and is intended as the implementation reference for the India-only source migration.

It intentionally keeps the US lane separate. The immediate objective is:

- remove FMP from India-related code and assumptions
- strengthen NSE/BSE ingestion
- keep Yahoo as India fallback only

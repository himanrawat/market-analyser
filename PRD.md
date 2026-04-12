# Product Requirements Document
## Personal Stock Picker & Monthly Rebalance Tool

**Owner:** Himanshu
**Version:** 1.2 (v1 scope locked, with hybrid India data-lane update)
**Last updated:** April 12, 2026
**Status:** Approved for build

### Changelog
- **v1.2** — Changed India fundamentals architecture to a hybrid lane: official NSE filings first, BSE fallback, vendor fallback only as a last resort. Added self-computed India ratios/valuation as a core design requirement. Removed the assumption that FMP Starter is the production source of truth for Indian quarterly fundamentals.
- **v1.1** — Added: configurable picks-per-bucket, view-more expandable list, manual filters (cap/risk/sector/country), valuation sort (P/E, P/B), refresh-prices button, two-stream news system, market-shock detection with red banner, skip-this-month action.
- **v1.0** — Initial scope lock.

---

## 1. Background & Problem Statement

I am a salaried frontend engineer in India. I invest in Indian stocks via Zerodha Kite and US stocks via HDFC/Vested. I am a long-horizon investor, not a trader — my holding period ranges from a few weeks to several years. I deploy ₹10,000–₹20,000 of fresh capital every month from my salary.

Today, my stock-picking is ad-hoc. I don't have the time, the data, or the structured methodology to consistently evaluate ~1000 stocks across two markets every month against fundamental, technical, macro, sentiment, and event-driven criteria. The result is inconsistent decisions, recency bias, and a portfolio that is more "things I happened to read about" than "best available risk-adjusted opportunities."

This app exists to remove research effort, enforce discipline, and let a rules-based system surface the best monthly buy/sell/hold actions for me to execute manually in my brokers.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1.** Eliminate the need for me to do any manual stock research before my monthly investment cycle.
- **G2.** Surface a consistent, rules-based, auditable list of buy/sell/add/hold actions on the 7th of every month.
- **G3.** Cover both Indian (Nifty 500) and US (S&P 500) markets in a single workflow.
- **G4.** Support four distinct investment philosophies (Quality+Value, Momentum, Quality+Momentum, Dividend Growth) so I can choose which ones to act on.
- **G5.** Build a permanent record of every decision and its reasoning, so I can review my own behavior over years.
- **G6.** Stay personal, local, and cheap — total monthly running cost under ₹2,000.

### 2.2 Non-Goals (v1)

- **NG1.** Not a trading platform. The app does not place orders. I execute manually in Kite and Vested.
- **NG2.** No intraday, day trading, scalping, or futures/options. Cash equity only.
- **NG3.** No live tick data. End-of-day data is sufficient for monthly rebalancing.
- **NG4.** No backtesting engine in v1 (deferred to v2).
- **NG5.** No multi-user, no auth, no commercial features. Single-user personal tool.
- **NG6.** No AI/LLM as the stock-picker. LLMs may be used as tools (e.g. headline summarization) but never as the source of buy/sell decisions.
- **NG7.** No Twitter/Reddit/social sentiment. Too noisy for a monthly cadence.
- **NG8.** No crypto. Different asset class, separate problem.

---

## 3. Target User

A single user: me.

- Frontend engineer, ~4+ years experience, comfortable with TypeScript, React, Next.js. Willing to learn Python for the data pipeline.
- Long-term investor, not a trader. Risk tolerant in concept but untested through a real bear market.
- Investment experience: intermediate. Knows the vocabulary, has read foundational books, has not yet run a rules-based system.
- Time available for investing: ~30 minutes per month, on the 7th.

---

## 4. Core User Flow

### 4.1 The monthly cycle

1. **5th of the month, evening:** I do nothing. The app does nothing visible.
2. **6th of the month, overnight:** Pipeline runs automatically. Fetches all data, scores all stocks, generates 8 ranked lists (4 buckets × 2 countries), diffs against my current portfolio, writes results to local database.
3. **7th of the month, morning:** I receive a Telegram or email digest with a summary. I open the app.
4. **7th of the month, ~20 minutes:**
   - I review the 8 ranked lists.
   - I open the action screen, which tells me exactly what to BUY, SELL, ADD, TRIM, or HOLD.
   - I configure how this month's ₹10–20k splits across the buckets I want to act on.
   - I execute the trades manually in Kite (India) and Vested (US).
   - I tick off each action in the app to mark it executed. Trade journal entries are auto-created.
5. **Rest of the month:** I do nothing. The app does nothing.

### 4.2 The mid-month cycle (optional)

Occasionally, between rebalances, I may want to look up a specific stock, check my current portfolio, or read about an upcoming macro event. The app supports this as a passive lookup tool — no notifications, no nudges.

---

## 5. Functional Requirements

### 5.1 Data ingestion & universe

- **F-1.1** The system maintains a universe of stocks: Nifty 500 (India) and S&P 500 (US). Constituent lists refreshed quarterly.
- **F-1.2** The system fetches daily OHLCV price data for every stock in the universe, going back 3 years on first run, then daily increments.
- **F-1.3** The system fetches quarterly fundamentals for every stock: revenue, earnings, EPS, ROE, ROCE, debt/equity, free cash flow, P/E, PEG, P/B, dividend yield, payout ratio.
- **F-1.3.1** For **India**, quarterly fundamentals use a **hybrid source priority**: official **NSE filings first**, **BSE fallback** if NSE is missing or unusable, and vendor fallback only as a last resort.
- **F-1.3.2** For **US**, quarterly fundamentals continue to use vendor APIs (FMP primary, yfinance fallback where needed).
- **F-1.3.3** For **India**, promoter holding comes from official shareholding disclosures, not vendor summary fields.
- **F-1.3.4** The system computes India-specific derived metrics locally when not directly available from the source: ROE, ROCE, debt/equity, free cash flow, payout ratio, dividend yield, P/E, P/B, EV/EBITDA.
- **F-1.4** The system fetches recent news headlines (last 30 days) for every stock at each rebalance run.
- **F-1.5** The system fetches upcoming events for every stock: next earnings date, ex-dividend date, corporate actions.
- **F-1.6** The system fetches macro snapshots: Fed funds rate, RBI repo rate, US/India CPI, USD/INR, India VIX, US VIX, 10-year treasury yields, oil price.
- **F-1.7** All fetched data is cached in a local SQLite database with timestamps. The pipeline never re-fetches data already present and fresh.

### 5.2 Universe filter

Before scoring, the universe is reduced by hard filters:

- **F-2.1** Drop any stock with market cap < ₹5,000 cr (India) or < $2B (US).
- **F-2.2** Drop any stock with average daily volume < ₹10 cr (India) or < $10M (US).
- **F-2.3** Drop any stock listed less than 3 years.
- **F-2.4** Drop any stock currently suspended, in F&O ban (India), or under regulatory investigation.
- **F-2.5** The filter reduces the working set from ~1000 to ~300–400 stocks.

### 5.3 Scoring engine — four buckets

Each surviving stock is scored 0–100 against four bucket profiles independently. A stock can qualify for 0, 1, 2, or 3 buckets simultaneously.

#### F-3.1 Quality + Value bucket

| Factor | Weight | Logic |
|---|---|---|
| ROE 5-yr avg | 15 pts | >20% = full, scaled down to 0 at <8% |
| Debt/Equity | 10 pts | <0.5 = full, >2 = zero (excluded for banks/NBFCs) |
| Earnings growth 5-yr CAGR | 10 pts | >15% = full |
| FCF positive & growing | 10 pts | Positive last 3 years = full |
| P/E vs sector median | 15 pts | Below sector median = full, above = zero |
| P/E vs own 5-yr median | 10 pts | Below own median = full |
| Dividend yield | 5 pts | >1% = full |
| Promoter holding stable/rising (India) | 5 pts | India only |
| **Disqualifiers** | — | High debt, declining margins 3 quarters in a row, P/E in top quintile of sector |

#### F-3.2 Momentum / Trend bucket

| Factor | Weight | Logic |
|---|---|---|
| 12mo-1mo price momentum | 25 pts | Top quintile = full (academic momentum factor) |
| Above 200 DMA | 10 pts | Yes = full |
| 50 DMA above 200 DMA | 10 pts | Yes = full (Stage 2 uptrend) |
| Distance from 52-week high | 10 pts | Within 15% of 52wk high = full |
| Volume trend (rising on up days) | 10 pts | Up-volume > down-volume = full |
| Recent earnings beat | 10 pts | Last quarter actual > estimate by >5% |
| Sales growth latest quarter | 15 pts | >15% YoY = full |
| RSI 14 | 10 pts | 50–80 = full, >85 = penalty |
| **Disqualifiers** | — | Below 200 DMA, broken trend, recent earnings miss |

#### F-3.3 Quality + Momentum bucket (the recommended primary strategy)

| Factor | Weight | Logic |
|---|---|---|
| ROE 5-yr avg | 15 pts | >15% = full |
| Debt/Equity | 10 pts | <1 = full |
| Earnings growth 3-yr CAGR | 15 pts | >15% = full |
| FCF positive & growing | 10 pts | Positive last 3 years = full |
| 12mo-1mo price momentum | 20 pts | Top quintile = full |
| Above 200 DMA | 10 pts | Yes = full |
| 50 DMA above 200 DMA | 10 pts | Yes = full |
| Distance from 52-week high | 10 pts | Within 20% = full |
| **Disqualifiers** | — | Either fundamental quality OR price trend failure disqualifies |

#### F-3.4 Dividend Growth bucket

| Factor | Weight | Logic |
|---|---|---|
| Years of consecutive dividend increases | 25 pts | 10+ yrs (US) / 5+ yrs (India) = full |
| Dividend growth rate 5-yr CAGR | 20 pts | >10% = full |
| Current dividend yield | 15 pts | >1.5% = full |
| Payout ratio | 15 pts | <60% = full, >80% = zero |
| FCF coverage of dividend | 15 pts | FCF > 1.5× dividend = full |
| Earnings stability (low variance) | 10 pts | Low coefficient of variation = full |
| **Disqualifiers** | — | Any dividend cut in last 10 years, payout ratio > 80%, declining FCF |

### 5.4 Guardrails

Applied to every ranked list before it's shown to me:

- **F-4.1** Sector cap: maximum 3 stocks from any single sector in any top-10 list.
- **F-4.2** Earnings blackout: any stock with earnings within 5 days is removed from the list, replaced with the next-highest-scoring qualifier.
- **F-4.3** Hysteresis buffer: a stock currently held only drops out of the list if its score falls more than 10 points below the cutoff. Prevents churn from minor month-to-month score wiggles.
- **F-4.4** Macro veto flag: if Nifty 50 or S&P 500 is below its 200 DMA, the entire month's lists are tagged "Defensive Regime — consider reducing new buys." The lists are still shown; the decision stays with me.
- **F-4.5** **View-more expandable list:** Each ranked list defaults to top 10 (action set), with an expandable "Show more" affordance revealing all qualifying stocks beyond the top 10. Stocks 11+ are visually de-emphasized (grayed out, smaller, no BUY/SELL action buttons) — they exist for browsing and curiosity, not for monthly action. The discipline rule is preserved: only the top N (default 10) are actionable.
- **F-4.6** **Configurable picks-per-bucket** (Settings only, not in main flow): Allowed values 5 / 10 / 15 / 20. Default 10. Set once and forget — intentionally tucked away to discourage month-to-month tweaking.
- **F-4.7** **Manual filter layer** on every ranked list:
  - **Market cap:** Large / Mid / Small / All (multi-select)
  - **Country:** India only / US only / Both
  - **Sector:** include/exclude (multi-select)
  - **Risk preset:** Conservative / Balanced / Aggressive
    - *Conservative* = Large cap only, D/E < 0.5, dividend yield > 1%, above 200 DMA
    - *Balanced* = Large + Mid cap, D/E < 1, no other constraints
    - *Aggressive* = All caps, no debt constraint, momentum bucket allowed
  Filters operate **on top of** the locked top-N — they hide rows from view, they do not expand the candidate pool. A counter shows "Showing X of N" so I always know what's filtered out.
- **F-4.8** **Valuation sort:** Sort the visible list by P/E (low to high or reverse) or P/B (low to high or reverse). This is the financially correct interpretation of "cheap to expensive" — based on earnings and book value, not absolute share price. Note: raw share price sort is intentionally excluded because share price absent share count is not a meaningful signal of value.

### 5.5 Macro & event overlay

- **F-5.1** Sector tilt computation: each sector receives a tilt of +1, 0, or -1 based on macro signals (e.g. rising rates → Financials +1, Real Estate -1; rising USD/INR → IT +1, Importers -1). Stocks inherit their sector's tilt.
- **F-5.2** Sector tilt is shown as a flag on the stock card but does NOT change the score. It is informational.
- **F-5.3** Event flags: stocks with upcoming earnings within 14 days display an event badge. Stocks with recent earnings beats display a positive badge.

### 5.6 Portfolio diff & action screen

- **F-6.1** The system reads my current holdings from the local SQLite portfolio table.
- **F-6.2** For each bucket and country, it generates an action table with columns: Stock | Current Qty | Current Value | Target Action (BUY / SELL / ADD / TRIM / HOLD) | Suggested Amount | Reason.
- **F-6.3** The diff logic:
  - In top 10 + already own = HOLD (or ADD if underweight relative to equal weight)
  - In top 10 + don't own = BUY
  - Not in top 10 + own + score dropped > 10 points below cutoff = SELL
  - Not in top 10 + own + score still close to cutoff = HOLD (hysteresis)
- **F-6.4** A capital deployment planner takes my fresh capital input (₹10–20k) plus any SELL proceeds and splits the total across the BUY and ADD actions.
- **F-6.5** Bucket allocation sliders let me set what % of monthly capital goes to each of the 4 buckets. Default: 60% Quality+Value, 40% Quality+Momentum, 0% Momentum, 0% Dividend Growth.
- **F-6.6** Each action row has an "Executed" checkbox. Ticking it creates an auto-filled trade journal entry and updates the portfolio table.
- **F-6.7** **Refresh prices button:** On the action screen, a manual "Refresh prices" button pulls 15-minute-delayed quotes (free, via yfinance) for the ~20 stocks in the action list and updates the displayed current price column. The scores do NOT recompute — they remain locked to the rebalance run from the 6th. This addresses the staleness gap between the pipeline run (6th evening) and execution time (7th morning) without introducing any cost or temptation toward intraday reactivity.
- **F-6.8** **Skip this month button:** A first-class action labeled "Skip this month's rebalance" lives on the action screen. Clicking it requires a one-line journal reason (logged in trade journal) and marks the month as deliberately skipped. No trades, no actions, no nudges. The next month's rebalance proceeds normally. This exists because the most valuable button in long-term investing is "do nothing" and the app should make that a first-class option, not hide it.

### 5.7 Per-stock detail card

Accessible by clicking any stock in any list. Tabbed interface:

#### F-7.1 Overview tab
Price, market cap, sector, P/E, P/B, ROE, D/E, dividend yield, 52-week high/low, business description, current bucket membership.

#### F-7.2 Sentiment tab
Last 30-day sentiment trend, headline volume vs 12-week baseline, sentiment score breakdown (positive/negative/neutral counts).

#### F-7.3 Forecasts tab
Analyst price targets (high/low/avg), buy/hold/sell consensus, EPS estimates for next 4 quarters.

#### F-7.4 Peers tab
5–8 similar companies in the same sector, side-by-side comparison: P/E, ROE, growth rate, market cap, current bucket membership.

#### F-7.5 Holding tab
My personal position: quantity, average buy price, current value, unrealized P&L, % of portfolio, days held, LTCG/STCG status (India).

#### F-7.6 Events tab
Next earnings date, ex-dividend date, dividend amount, recent splits, upcoming corporate actions.

#### F-7.7 News tab
Last 10–20 headlines with source, date, link, sentiment color.

#### F-7.8 Score breakdown
Radar chart or 4-bar visualization showing how the stock scored against each of the 4 buckets, with the contributing factors expandable.

#### F-7.9 Plain-English explanation
Auto-generated paragraph: "Why this stock made the list" — composed from the highest-scoring factors. Example: *"This stock is in the Quality+Momentum bucket because: 5-year ROE is 22%, debt/equity is 0.3, earnings growing at 18% CAGR. Price is 12% above 200 DMA and within 8% of 52-week high. Sector (IT) currently has a positive macro tilt due to weak rupee."*

### 5.8 Portfolio tracker

- **F-8.1** Manual entry form for adding holdings (ticker, qty, avg price, buy date, country).
- **F-8.2** CSV import is NOT in v1 — manual entry only. (Deferred to v2.)
- **F-8.3** Holdings view showing per-stock cost basis, current value, P&L, % of portfolio, days held.
- **F-8.4** Total portfolio value, % return, vs Nifty 50 and S&P 500 benchmarks.
- **F-8.5** Sector allocation pie chart with concentration warnings if any sector exceeds 25%.
- **F-8.6** India vs US allocation breakdown.
- **F-8.7** LTCG/STCG flag (India): warns if any holding is at 11 months held to avoid premature short-term capital gains tax.

### 5.9 Trade journal

- **F-9.1** Each executed action creates a journal entry pre-filled with: ticker, date, action type, suggested price, the bucket it came from, and the auto-generated thesis.
- **F-9.2** Manual fields on the entry: actual fill price, optional free-text notes.
- **F-9.3** On exit (SELL or TRIM), the app prompts: "What did you learn from this trade?" and requires at least a one-line answer.
- **F-9.4** Monthly review screen: win rate, average holding period, biggest winner, biggest loser, lessons logged.

### 5.10 Macro & event dashboard (always visible header/sidebar)

- **F-10.1** Index strip: Nifty 50, Sensex, S&P 500, Nasdaq with 1d / 1m / 1y change.
- **F-10.2** Volatility gauges: India VIX, US VIX.
- **F-10.3** Currency: USD/INR with 1m trend.
- **F-10.4** Market regime indicator: Risk-On / Caution / Risk-Off based on 200 DMA rule.
- **F-10.5** Upcoming events strip: next 14 days of Fed/RBI meetings, CPI/GDP releases, big earnings from my watchlist.

### 5.11 Settings & configuration

- **F-11.1** Tunable factor weights per bucket (sliders).
- **F-11.2** Universe selector toggle (Nifty 50 / Nifty 500 / S&P 100 / S&P 500).
- **F-11.3** Rebalance day setting (default 7th, auto-shifts to next trading day if 7th is a holiday).
- **F-11.4** Notification toggle: Telegram or email digest on rebalance day + immediate alerts for RED-banner shock events.
- **F-11.5** Bucket allocation defaults.
- **F-11.6** Picks-per-bucket selector (5 / 10 / 15 / 20). Tucked under "Advanced" to discourage frequent tweaking.
- **F-11.7** News stream toggles: enable/disable stock-specific news, enable/disable market-shock detection independently.

### 5.12 Behind the scenes

- **F-12.1** Local SQLite database stores all data: stocks, prices, fundamentals, news, events, holdings, monthly snapshots, trade journal.
- **F-12.2** Every monthly rebalance run is preserved as a snapshot. I can audit any past month's lists and reasoning.
- **F-12.3** Data caching layer prevents redundant API calls.
- **F-12.4** Pipeline runs as a scheduled job (cron or APScheduler) on the 6th of each month.

### 5.13 News & market-shock detection

The news system has **two completely separate streams** with different sources, polling cadences, and UI treatments. Mixing them is a UX failure mode I want to avoid.

#### F-13.1 Stream 1 — Stock-specific news (informational)

- **F-13.1.1** Polled every 30 minutes for ~30 watched stocks: my current holdings + this month's top picks across all 4 buckets.
- **F-13.1.2** Source: FMP `/stock_news` endpoint (included in FMP Starter, no extra cost).
- **F-13.1.3** Categorized by type: Earnings / Management / Regulatory / M&A / Dividend / Other. Filter chips at the top of the news panel let me toggle categories.
- **F-13.1.4** Each news item is sentiment-scored via VADER (positive / neutral / negative) and color-coded.
- **F-13.1.5** Displayed in a "News Feed" panel accessible from the main dashboard. **NOT pushed as notifications.** I check it when I want to.
- **F-13.1.6** **Discipline rule (enforced via UX copy, not code):** stock news informs my next 7th-of-month decision. It does not trigger an immediate trade. The news panel header says exactly this, in plain language.

#### F-13.2 Stream 2 — Market-shock detection (alarm)

- **F-13.2.1** Polled every 30 minutes from global headlines (FMP general news + free NewsAPI tier as backup).
- **F-13.2.2** **Two-signal detection logic** to minimize false alarms:
  - **Signal A (keyword match):** Curated keyword list across categories: war / military / invasion / missile / strike, pandemic / outbreak / virus / lockdown, sovereign default / banking crisis / systemic bank failure, emergency rate decision / unscheduled Fed / unscheduled RBI, terror attack / explosion in major financial center, oil shock / OPEC emergency.
  - **Signal B (volatility confirmation):** India VIX or US VIX up >20% intraday.
  - **Escalation rule:** Both signals firing within the same 24h window → **RED banner**. Only one signal firing → **YELLOW banner** (caution, not alarm).
- **F-13.2.3** **RED banner UI:** Red horizontal banner across the top of every screen in the app, displaying the triggering headline + timestamp + dismiss-for-24h option. Cannot be permanently dismissed; reappears on every new shock event.
- **F-13.2.4** **YELLOW banner UI:** Same position, yellow color, less visually aggressive. Indicates "potential developing situation, monitor."
- **F-13.2.5** **Auto-Risk-Off override:** If a RED-banner event has fired in the 14 days preceding the next rebalance run, the macro overlay automatically flips to Risk-Off **regardless** of whether the 200 DMA rule says otherwise. The next rebalance is tagged "Shock Regime — review carefully" and the action screen highlights the "Skip this month" button.
- **F-13.2.6** **Behavioral rule, encoded in UX copy and journal prompts:**
  > **Red banner = pause new buys for the rest of the month. Red banner ≠ sell what I already own.**

  This rule is shown on the banner itself, on the action screen, and in any "Skip this month" confirmation dialog. Holdings ride through shocks; only new deployment is paused.
- **F-13.2.7** **False-alarm acknowledgment:** The PRD acknowledges that over a 10-year window, the shock detector will likely fire 4–6 true positives and 15–25 false positives. This is acceptable because: (a) false positives only cause me to pause new buys for a month, which is essentially costless, and (b) the rule explicitly forbids selling holdings on a banner alone, which is where real damage would happen.
- **F-13.2.8** **Shock event log:** Every banner trigger is logged with timestamp, headline, signal-A keywords matched, VIX values at trigger, and outcome (was the next 30-day market move > -5%? Tag as "true" or "false" alarm in retrospect for future review).

---

## 6. Data Sources & Integrations

### 6.1 Hybrid India data lane — removals, replacements, additions

**Removed from the production data-trust model**
- FMP as the assumed source of truth for **Indian** quarterly fundamentals.
- yfinance as the intended long-term fallback for **Indian** production fundamentals. It remains an emergency fallback only, not a quality target.

**Replaced**
- **Indian quarterly fundamentals:** `FMP/yfinance` → `NSE filings first -> BSE fallback -> vendor last resort`
- **Indian promoter holding:** vendor summary fields → official shareholding pattern filings
- **Indian ratio ownership:** vendor-computed ratios only → locally computed ratios from official statements when needed

**Added**
- Official exchange-filed India fundamentals lane
- Official exchange-filed India shareholding lane
- Local ratio/valuation computation for India
- Stronger provider abstraction so India and US can use different source strategies without changing scoring/UI logic

| Source | Purpose | Cost | Critical? |
|---|---|---|---|
| **NSE Corporate Filings / XBRL / Integrated Filing** | **Primary source of truth for India fundamentals and shareholding** | Free | Yes |
| **BSE Corporate Filings / XBRL** | Fallback source for India fundamentals when NSE data is unavailable or incomplete | Free | Yes |
| **Financial Modeling Prep** | **US** fundamentals, earnings calendar, stock-specific news, peers, analyst forecasts, dividends, general market news; India vendor fallback only where necessary | ~$22/mo (~₹1,800) | Yes |
| **yfinance (Python lib)** | Daily OHLCV prices, VIX, India VIX, currencies, 15-min-delayed quotes for refresh button, emergency fallback for missing profile/fundamental fields | Free | Yes |
| **FRED API** | US macro (Fed funds, CPI, GDP, treasury yields) | Free | Yes |
| **RBI DBIE (small scraper)** | India macro (repo rate, India CPI) | Free | Yes |
| **NewsAPI.org (free dev tier)** | Backup global news source for market-shock detection (24h delayed is acceptable for shock detection) | Free | Backup |
| **Hardcoded events.yaml** | Fed FOMC dates, RBI MPC dates, scheduled CPI/NFP releases — updated yearly | Free | Yes |
| **VADER sentiment** | Headline sentiment scoring | Free (pip install) | Yes |
| **Telegram Bot API** | Monthly digest delivery + RED banner shock alerts | Free | Optional |

**Total recurring cost: currently still ~₹1,800/month.** The hybrid rollout reduces dependency on paid vendor coverage for India, but the current working assumption is that FMP is still retained for US data and stock-detail enrichments. Real-time price streaming explicitly NOT purchased — see section 9 Permanently Excluded.

---

## 7. Technical Architecture (high-level)

### 7.1 Components

- **Data pipeline** (Python) — runs monthly, fetches and scores everything, writes to SQLite.
- **Database** (SQLite) — single file, stores all data, stocks, snapshots, portfolio, journal.
- **Web UI** (Next.js + TypeScript) — reads from SQLite (via a thin API layer), renders all dashboards.
- **API layer** (FastAPI or Next.js API routes wrapping a Python subprocess) — bridges the UI and the Python pipeline / SQLite.
- **Scheduler** (cron on host, or APScheduler in Python) — triggers the pipeline on the 6th.
- **Notifier** (Telegram bot or SMTP email) — sends the monthly digest.

### 7.2 Hosting

Cheap VPS (DigitalOcean / Hetzner / Railway), ~₹500/mo. Single Linux VM running:
- Python pipeline as a cron job
- Next.js app as a systemd service
- SQLite as a local file
- Caddy or nginx as reverse proxy with HTTPS

Alternatively v1 can run entirely on my laptop with manual pipeline triggers, deferred to VPS once stable.

### 7.3 Tech stack summary

| Layer | Technology |
|---|---|
| Pipeline | Python 3.11+, pandas, pandas-ta, yfinance, fredapi, requests, vaderSentiment, SQLAlchemy, exchange-filings parsers/importers |
| Database | SQLite (v1), upgrade to PostgreSQL only if/when needed |
| Backend API | FastAPI (Python) |
| Frontend | Next.js 14+, TypeScript, Tailwind, shadcn/ui, Recharts or Lightweight Charts |
| Scheduler | cron (Linux) |
| Notifications | Telegram Bot API |
| Hosting | DigitalOcean droplet or equivalent (~₹500/mo) |

---

## 8. Feature List (v1.1 — locked)

51 features across 10 areas. Full list:

### Core monthly engine (1–8)
1. Automated pipeline run on the 6th of every month
2. Universe filter (Nifty 500 + S&P 500 minus illiquid/young stocks)
3. Four scoring buckets (Quality+Value, Momentum, Quality+Momentum, Dividend Growth)
4. Top N per bucket per country (default 10, configurable 5/10/15/20)
5. Guardrails (sector cap, earnings blackout, hysteresis)
6. Macro overlay (Risk-On / Caution / Risk-Off regime)
7. View-more expandable list (top N actionable + grayed-out browse beyond)
8. Manual filter layer (cap, country, sector, risk preset, P/E sort, P/B sort)

### 7th-of-the-month action screen (9–14)
9. Portfolio diff view (BUY/SELL/ADD/TRIM/HOLD per stock)
10. Capital deployment planner
11. Bucket allocation sliders
12. Mark-as-executed checkboxes
13. Refresh prices button (15-min delayed, on demand)
14. Skip this month button (first-class "do nothing" action with journal logging)

### Per-stock detail card (15–22)
15. Five-lens score breakdown (radar/bars)
16. Bucket membership display (which of 4 buckets the stock qualifies for)
17. Plain-English "why this stock" explanation
18. Price chart with 50/200 DMA + RSI overlay
19. Fundamentals trend mini-charts (8–12 quarters)
20. Recent news headlines, sentiment colored
21. Upcoming events
22. Sector + macro tilt display

### Per-stock tabbed views (sub-features of 15–22)
- Overview tab
- Sentiment tab
- Forecasts tab
- Peers tab
- Holding tab
- Events tab
- News tab

### Portfolio tracker (23–28)
23. Manual entry of current holdings
24. Cost basis, current value, unrealized P&L
25. Sector allocation pie chart
26. India vs US allocation
27. Benchmark comparison (vs Nifty 50 and S&P 500)
28. LTCG vs STCG flag (India)

### Trade journal (29–32)
29. Auto-pre-filled entries from rebalance actions
30. Manual fill price + free-text notes
31. Exit prompt: "What did you learn?"
32. Monthly review screen

### Always-visible dashboard (33–37)
33. Index strip (Nifty 50, Sensex, S&P 500, Nasdaq)
34. Volatility gauges (India VIX, US VIX)
35. USD/INR
36. Market regime indicator
37. Upcoming events strip (14 days)

### News & shock detection (38–44)
38. Stock-specific news feed (~30 watched stocks, polled every 30 min)
39. News category filters (Earnings / Management / Regulatory / M&A / Dividend / Other)
40. VADER sentiment color-coding on every headline
41. Market-shock detector (two-signal: keyword + VIX confirmation)
42. RED banner across all screens for confirmed shocks
43. YELLOW banner for single-signal caution events
44. Auto-Risk-Off override on next rebalance after RED event
45. Shock event log with retrospective true/false-positive tagging

### Settings (46–49)
46. Tunable factor weights per bucket
47. Universe selector
48. Rebalance day setting
49. Notification toggle (Telegram/email digest + shock alerts)

### Behind the scenes (50–51)
50. Local SQLite database with monthly snapshot history
51. Data caching layer

---

## 9. Out of Scope for v1

### Deferred to v2
- Backtesting engine
- Drawdown kill-switch / auto-defensive mode (the v1 shock detector is the lightweight version)
- What-if simulator (tweak weights against historical data)
- Mobile / PWA view
- Auto CSV import from Kite/Vested
- LLM-based sentiment scoring (replace VADER with Claude Haiku)
- Sector rotation analysis view
- FinBERT or transformer-based news classification (currently keyword-based)

### Permanently excluded
- Order placement via broker APIs
- **Live tick / real-time intraday price streaming.** Considered and explicitly rejected. Reason: hold horizon is weeks-to-years, decision moment is once per month, and academic research consistently shows higher checking frequency correlates with worse long-term returns for retail investors. Refresh button + 15-min-delayed quotes covers the only legitimate use case (fresh prices at execution time on the 7th).
- AI/LLM as primary stock-picker
- Twitter/Reddit sentiment (too noisy for monthly cadence)
- Crypto
- Auto-trading
- Multi-user / commercial features

---

## 10. Success Metrics

Because this is a personal tool, success is not measured in users or revenue. It's measured in behavior change and portfolio outcome.

### 10.1 Behavioral metrics (measured monthly)
- **M-1.** Time spent on stock research per month: target < 30 min (currently several hours, ad-hoc).
- **M-2.** % of months where I followed the rebalance plan: target > 80%.
- **M-3.** Trade journal entries completed: 100% of executed trades.

### 10.2 Portfolio metrics (measured quarterly, vs benchmark)
- **M-4.** Portfolio CAGR vs Nifty 50 + S&P 500 blended benchmark: target to match or beat over rolling 3-year periods.
- **M-5.** Max drawdown vs benchmark: target no worse than benchmark.
- **M-6.** Portfolio turnover: target < 30% annually (i.e. average holding period > 3 years).

### 10.3 System metrics (measured continuously)
- **M-7.** Pipeline run reliability: target > 95% successful runs on the 6th.
- **M-8.** Data freshness: 100% of fundamentals < 90 days old at rebalance time.

---

## 11. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | I panic-sell during a market drawdown and abandon the system | High | High | Trade journal forces reflection on every exit. 6-month minimum trial period agreed before judging performance. |
| R-2 | FMP API changes pricing or shuts down | Low | High | Build a clean abstraction layer; official NSE/BSE lane becomes the source of truth for India, yfinance remains price fallback, and vendor dependence is concentrated mainly in US + enrichments. |
| R-14 | Official NSE/BSE filing formats or anti-bot behavior change | Medium | Medium | Keep provider abstraction strict, support both NSE and BSE, store normalized imports locally, and make vendor fallback explicit instead of silent. |
| R-3 | Scoring formulas overfit to recent market conditions | Medium | High | No backtesting in v1 means no overfitting opportunity. Formulas use textbook factor definitions, not optimized parameters. |
| R-4 | Sentiment lens generates noisy or wrong signals | High | Low | Sentiment is weighted lowest. It's informational on the stock card, not part of the score in v1. |
| R-5 | Pipeline fails silently on the 6th and I miss the rebalance | Medium | Medium | Telegram digest doubles as a heartbeat — no message means something broke. |
| R-6 | I tweak the formulas every month based on what would have worked last month | High | High | Settings UI is intentionally tucked away. A "lock weights for 6 months" toggle is added in v2. For v1: discipline. |
| R-7 | Tax implications of high turnover wipe out alpha | Medium | High | Hysteresis buffer (10 points) keeps turnover low. LTCG/STCG flag prevents premature sells. |
| R-8 | Vested has no API, so US portfolio sync is manual forever | Certain | Low | Manual entry is acceptable for ~10–20 US holdings. CSV import in v2 if it becomes painful. |
| R-9 | Survivorship bias in universe (current Nifty 500 ≠ historical Nifty 500) | Medium | Low (v1 has no backtest) | Becomes critical in v2 backtest; for v1, irrelevant since we trade forward only. |
| R-10 | Stock-specific news feed tempts me to trade between rebalances | High | Medium | Discipline rule baked into news panel UX copy: "News informs the next 7th, not today." Trade journal will catch any off-cycle trades and force a "why" entry. |
| R-11 | RED banner triggers panic-selling of existing holdings | Medium | High | Behavioral rule explicitly displayed on every banner: "Pause new buys, do NOT sell holdings." Skip-this-month button is the only sanctioned response. |
| R-12 | False-positive shock alerts cause "alarm fatigue" and I start ignoring them | High | Medium | Two-signal detection (keyword + VIX) keeps false positive rate manageable. Retrospective true/false tagging in shock event log builds calibration over time. |
| R-13 | News API rate limits hit during a real shock when I most need it | Low | Medium | Cache aggressively, fall back to NewsAPI free tier if FMP fails, fall back to manual news check via broker apps as last resort. |

---

## 12. Implementation Phases

High-level phasing — detailed week-by-week plan to be produced separately.

### Phase 1: Data foundation (weeks 1–2)
- Set up Python project, SQLite schema
- FMP integration: US fundamentals, news, events, peers
- yfinance integration: prices, currencies, VIX, 15-min-delayed quote helper
- FRED integration: US macro
- RBI scraper: India macro
- NewsAPI free-tier integration as backup news source
- Universe ingestion: Nifty 500 + S&P 500 ticker lists
- Data caching layer

### Phase 1.5: Hybrid India fundamentals lane
- Add official India fundamentals provider abstraction
- NSE filings as primary India source
- BSE filings as fallback India source
- Shareholding ingestion for promoter holding
- Local derived-metrics computation for India
- Vendor merge/fallback only when official data is missing or incomplete

### Phase 2: Scoring engine (weeks 3–4)
- Universe filter implementation
- Quality+Value scoring formula
- Momentum scoring formula
- Quality+Momentum scoring formula
- Dividend Growth scoring formula
- Guardrails (sector cap, earnings blackout, hysteresis)
- Macro overlay (regime + sector tilts)
- Monthly snapshot persistence

### Phase 3: Frontend foundation (weeks 5–6)
- Next.js project setup, Tailwind, shadcn/ui
- FastAPI backend exposing SQLite to UI
- Always-visible macro/event dashboard
- 8 ranked lists view (4 buckets × 2 countries) with view-more expansion
- Manual filter layer (cap, country, sector, risk preset, P/E sort, P/B sort)
- Per-stock detail card with all 7 tabs

### Phase 4: Portfolio + actions (week 7)
- Manual portfolio entry
- Portfolio diff logic
- Action screen with capital deployment planner
- Refresh prices button
- Skip this month button
- Mark-as-executed flow
- Trade journal foundations

### Phase 5: News, shock detection, polish (week 8)
- Stock-specific news feed (Stream 1)
- Market-shock detector with two-signal logic (Stream 2)
- RED / YELLOW banner UI on all screens
- Auto-Risk-Off override on next rebalance after shock
- Cron scheduler on VPS
- Telegram digest notifier + shock alert push
- Settings UI (factor weights, picks-per-bucket, news toggles)
- End-to-end testing with real data
- First live monthly rebalance

**Target v1.1 completion: 8 weeks of part-time evening/weekend work.**

---

## 13. Open Questions

None. All major decisions are locked:

- ✅ Universe: Nifty 500 + S&P 500
- ✅ Buckets: Quality+Value, Momentum, Quality+Momentum, Dividend Growth — segregated, not blended
- ✅ Initial allocation: 60% Quality+Value, 40% Quality+Momentum
- ✅ Country split: 10 each, separate (not combined)
- ✅ Single user, no auth
- ✅ Decision support only, no order execution
- ✅ Data lane: hybrid
- India: official NSE filings first, BSE fallback, vendor last resort
- US: FMP primary + yfinance fallback
- ✅ Hosting: VPS (~₹500/mo)
- ✅ Stack: Python pipeline + Next.js UI hybrid
- ✅ Rebalance day: 7th (with auto-shift for holidays)
- ✅ Picks per bucket: 10 default, configurable 5/10/15/20
- ✅ View-more: expandable list, top N actionable + grayed-out browse beyond
- ✅ Filter layer: cap, country, sector, risk preset, P/E sort, P/B sort
- ✅ Real-time prices: NO (refresh button + 15-min delayed instead)
- ✅ News: two streams (stock-specific feed + market-shock banner)
- ✅ Shock detection: two-signal (keyword + VIX confirmation)
- ✅ Skip-this-month: first-class action

---

## 14. Appendix

### 14.1 Glossary

- **Bucket** — One of the four investment styles (Quality+Value, Momentum, Quality+Momentum, Dividend Growth). Each has its own scoring formula.
- **Hysteresis buffer** — A grace zone (10 points) that prevents a held stock from being sold just because it dropped slightly out of the top 10 this month.
- **12mo-1mo momentum** — The academic momentum factor: total return over the last 12 months, minus the return of the most recent 1 month. The "minus 1 month" filters out short-term mean reversion.
- **Stage 2 uptrend** — Weinstein's term for a stock where 50 DMA is above 200 DMA and price is above both. The least risky time to buy a momentum stock.
- **Risk-On / Risk-Off regime** — Market state based on whether the broad index is above (Risk-On) or below (Risk-Off) its 200 DMA.
- **LTCG / STCG (India)** — Long-Term and Short-Term Capital Gains. Holdings sold after 1 year qualify for lower LTCG tax rate. Selling at 11 months is a costly mistake the app warns against.
- **FCF** — Free Cash Flow. Operating cash flow minus capex. The truest measure of a business's earnings power.
- **View-more / actionable vs browse** — The top N stocks per bucket are "actionable" (full color, BUY/SELL buttons). Stocks 11+ revealed via the view-more affordance are "browse only" (grayed out, no action buttons). The discipline rule is that monthly trades only come from the actionable set.
- **Two-signal shock detection** — A market-shock alert requires both a keyword match in headlines AND a VIX spike >20%. Either signal alone produces a yellow caution banner; both signals together produce a red alert banner.
- **Refresh prices button** — On-demand pull of 15-min-delayed quotes for the action list. Updates displayed prices but never recomputes scores. Bridges the staleness gap between pipeline run (6th evening) and execution (7th morning).
- **Skip this month** — A first-class action to deliberately do nothing in a given month. Requires a one-line journal reason. Resets the next month to normal.

### 14.2 Reading list (for context, not required)

- *The Intelligent Investor* — Benjamin Graham (foundational value investing)
- *One Up On Wall Street* — Peter Lynch (practical fundamental investing)
- *Trade Like a Stock Market Wizard* — Mark Minervini (momentum investing)
- *Quantitative Momentum* — Wesley Gray (the academic case for momentum)
- *Stocks for the Long Run* — Jeremy Siegel (the case for equities + dividend growth)
- AQR research papers on the Quality + Momentum factor combo (Asness, Frazzini, Pedersen)

---

**End of PRD v1.2**

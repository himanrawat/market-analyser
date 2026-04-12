/**
 * Typed API client for the Market Analyser FastAPI backend.
 * The UI consumes a small normalized layer here so page components stay simple
 * even when backend schemas evolve.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function get<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(BASE + path);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  console.log(`[API] GET ${url.toString()}`);
  const res = await fetch(url.toString(), { cache: "no-store" });
  console.log(`[API] GET ${path} → ${res.status}`);
  if (!res.ok) {
    console.error(`[API] GET ${path} failed: ${res.status} ${res.statusText}`);
    throw new Error(`GET ${path} → ${res.status}`);
  }
  const data = await res.json() as T;
  console.log(`[API] GET ${path} response:`, data);
  return data;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  console.log(`[API] POST ${BASE + path}`, body ?? "");
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  console.log(`[API] POST ${path} → ${res.status}`);
  if (!res.ok) {
    console.error(`[API] POST ${path} failed: ${res.status} ${res.statusText}`);
    throw new Error(`POST ${path} → ${res.status}`);
  }
  const data = await res.json() as T;
  console.log(`[API] POST ${path} response:`, data);
  return data;
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  console.log(`[API] PUT ${BASE + path}`, body ?? "");
  const res = await fetch(BASE + path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  console.log(`[API] PUT ${path} → ${res.status}`);
  if (!res.ok) {
    console.error(`[API] PUT ${path} failed: ${res.status} ${res.statusText}`);
    throw new Error(`PUT ${path} → ${res.status}`);
  }
  const data = await res.json() as T;
  console.log(`[API] PUT ${path} response:`, data);
  return data;
}

async function del(path: string): Promise<void> {
  console.log(`[API] DELETE ${BASE + path}`);
  const res = await fetch(BASE + path, { method: "DELETE" });
  console.log(`[API] DELETE ${path} → ${res.status}`);
  if (!res.ok) {
    console.error(`[API] DELETE ${path} failed: ${res.status} ${res.statusText}`);
    throw new Error(`DELETE ${path} → ${res.status}`);
  }
}

// ---------------------------------------------------------------------------
// UI-facing types
// ---------------------------------------------------------------------------

export type MacroRegime =
  | "risk_on"
  | "caution"
  | "risk_off"
  | "RISK_ON"
  | "CAUTION"
  | "RISK_OFF";
export type ShockBanner = "red" | "yellow" | "RED" | "YELLOW";
export type Bucket =
  | "quality_value"
  | "momentum"
  | "quality_momentum"
  | "dividend_growth";
export type Country = "IN" | "US";
export type ActionType =
  | "buy"
  | "sell"
  | "add"
  | "trim"
  | "hold"
  | "skip_month"
  | "BUY"
  | "SELL"
  | "ADD"
  | "TRIM"
  | "HOLD"
  | "SKIP_MONTH";

export interface IndexQuote {
  name: string;
  value: number | null;
  change_1d: number | null;
  change_1d_pct: number | null;
  change_1m_pct: number | null;
  change_1y_pct: number | null;
}

export interface VixReading {
  india_vix: number | null;
  us_vix: number | null;
  as_of: string | null;
}

export interface MacroSnapshot {
  regime: MacroRegime;
  shock_regime: boolean;
  fed_funds_rate: number | null;
  rbi_repo_rate: number | null;
  us_cpi_yoy: number | null;
  india_cpi_yoy: number | null;
  usd_inr: number | null;
  us_10y_yield: number | null;
  oil_price: number | null;
  as_of: string | null;
}

export interface UpcomingEvent {
  ticker: string | null;
  event_type: string;
  event_date: string;
  description: string | null;
}

export interface ShockBannerStatus {
  active: boolean;
  banner: ShockBanner | null;
  headline: string | null;
  triggered_at: string | null;
  dismissed_until: string | null;
}

export interface DashboardResponse {
  indices: IndexQuote[];
  vix: VixReading;
  macro: MacroSnapshot;
  upcoming_events: UpcomingEvent[];
  shock: ShockBannerStatus;
  as_of: string;
}

export interface RankedStock {
  ticker: string;
  name: string;
  sector: string | null;
  country: Country;
  score: number;
  rank: number;
  is_actionable: boolean;
  action: ActionType | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  dividend_yield: number | null;
  market_cap: number | null;
  reason: string | null;
  bucket_flags: string[];
  sector_tilt: number | null;
}

export interface BucketList {
  bucket: Bucket;
  country: Country;
  run_date: string | null;
  picks: number;
  actionable: RankedStock[];
  extended: RankedStock[];
  showing: number;
  total: number;
}

export interface RankedResponse {
  lists: BucketList[];
  run_date: string | null;
}

export interface ActionRow {
  ticker: string;
  bucket: Bucket;
  country: Country;
  action: ActionType;
  current_qty: number | null;
  current_value: number | null;
  current_price: number | null;
  score: number;
  rank: number | null;
  suggested_amount: number | null;
  suggested_qty: number | null;
  reason: string;
  factor_scores: Record<string, number>;
  executed: boolean;
}

export interface BucketAllocation {
  bucket: Bucket;
  pct: number;
  suggested_amount: number;
}

export interface DeploymentPlan {
  fresh_capital: number;
  sell_proceeds: number;
  total: number;
  allocations: BucketAllocation[];
  action_amounts: Record<string, number>;
  undeployed: number;
}

export interface ActionsResponse {
  run_date: string | null;
  rows: ActionRow[];
  plan: DeploymentPlan | null;
  shock_regime: boolean;
  macro_regime: MacroRegime;
}

export interface HoldingRow {
  id: number;
  ticker: string;
  name: string;
  country: Country;
  sector: string | null;
  qty: number;
  avg_price: number;
  buy_date: string;
  current_price: number | null;
  current_value: number | null;
  cost_basis: number;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  pct_of_portfolio: number | null;
  days_held: number | null;
  ltcg_warning: boolean;
  ltcg_status: string | null;
}

export interface SectorAllocation {
  sector: string;
  value: number;
  pct: number;
  over_concentrated: boolean;
}

export interface BenchmarkReturn {
  name: string;
  return_pct: number | null;
}

export interface PortfolioSummary {
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
  india_value: number;
  us_value: number;
  india_pct: number;
  us_pct: number;
  sector_allocations: SectorAllocation[];
  benchmarks: BenchmarkReturn[];
}

export interface PortfolioResponse {
  holdings: HoldingRow[];
  summary: PortfolioSummary;
}

export interface NewsArticle {
  id: number;
  ticker: string | null;
  headline: string;
  source: string | null;
  url: string | null;
  published_at: string;
  sentiment: "positive" | "neutral" | "negative";
  category: string | null;
  stream: string;
}

export interface NewsFeedResponse {
  items: NewsArticle[];
  total: number;
}

export interface JournalEntry {
  id: number;
  ticker: string;
  country: Country | null;
  action_date: string;
  action_type: ActionType;
  bucket: Bucket | null;
  suggested_price: number | null;
  fill_price: number | null;
  qty: number | null;
  thesis: string | null;
  notes: string | null;
  lesson: string | null;
  skipped_month: boolean;
}

export interface MonthlyReview {
  month: string;
  total_trades: number;
  buys: number;
  sells: number;
  win_rate: number | null;
  avg_holding_days: number | null;
  biggest_winner: string | null;
  biggest_winner_pct: number | null;
  biggest_loser: string | null;
  biggest_loser_pct: number | null;
  lessons_logged: number;
}

export interface SettingsResponse {
  picks_per_bucket: number;
  rebalance_day: number;
  universe_india: string;
  universe_us: string;
  notify_telegram: boolean;
  notify_email: boolean;
  shock_detection: boolean;
  stock_news: boolean;
  bucket_allocations: Record<Bucket, number>;
  factor_weights: Record<string, Record<string, number>>;
}

export interface PricePoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ScoreBucket {
  bucket: Bucket;
  score: number;
  factors: Record<string, number>;
  disqualified: boolean;
}

export interface StockDetailResponse {
  ticker: string;
  name: string;
  country: Country;
  sector: string | null;
  market_cap: number | null;
  current_price: number | null;
  week_52_high: number | null;
  week_52_low: number | null;
  description: string | null;
  fundamentals: {
    pe_ratio: number | null;
    pb_ratio: number | null;
    roe: number | null;
    debt_equity: number | null;
    dividend_yield: number | null;
    eps_growth_3y: number | null;
    fcf_positive: boolean | null;
  } | null;
  price_history: PricePoint[];
  scores: ScoreBucket[];
  plain_english: string | null;
  news: NewsArticle[];
  events: { event_type: string; event_date: string; description: string | null }[];
  forecasts: {
    analyst_count: number | null;
    buy_count: number | null;
    hold_count: number | null;
    sell_count: number | null;
    target_high: number | null;
    target_low: number | null;
    target_avg: number | null;
    current_price: number | null;
    consensus_rating: string | null;
    availability: string | null;
    note: string | null;
    quarterly_estimates: {
      period: string;
      fiscal_date: string | null;
      eps_estimate: number | null;
      revenue_estimate: number | null;
      analyst_count: number | null;
    }[];
  } | null;
  peers: {
    ticker: string;
    company_name: string | null;
    pe_ratio: number | null;
    roe: number | null;
    growth_rate: number | null;
    market_cap: number | null;
    bucket_membership: Bucket[];
  }[];
  peers_note: string | null;
  holding: HoldingRow | null;
  sentiment: {
    positive: number;
    neutral: number;
    negative: number;
    trend: string | null;
  } | null;
}

// ---------------------------------------------------------------------------
// Backend wire shapes
// ---------------------------------------------------------------------------

interface ApiActionRow extends Omit<ActionRow, never> {}

interface ApiBucketAllocation {
  bucket: Bucket;
  pct: number;
  amount: number;
}

interface ApiDeploymentPlan {
  fresh_capital: number;
  sell_proceeds: number;
  total_available: number;
  bucket_allocations: ApiBucketAllocation[];
  action_amounts: Record<string, number>;
  undeployed: number;
}

interface ApiActionsResponse {
  run_date: string | null;
  macro_regime: MacroRegime;
  shock_regime: boolean;
  buys: ApiActionRow[];
  sells: ApiActionRow[];
  adds: ApiActionRow[];
  holds: ApiActionRow[];
  plan: ApiDeploymentPlan | null;
}

interface ApiHoldingRow {
  id: number;
  ticker: string;
  name: string;
  sector: string | null;
  country: Country;
  qty: number;
  avg_buy_price: number;
  buy_date: string;
  current_price: number | null;
  current_value: number | null;
  cost_basis: number;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  days_held: number | null;
  ltcg_warning: boolean;
  pct_of_portfolio: number | null;
}

interface ApiPortfolioSummary {
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
  india_value: number;
  us_value: number;
  india_pct: number;
  us_pct: number;
  sector_allocation: SectorAllocation[];
  benchmarks: BenchmarkReturn[];
}

interface ApiPortfolioResponse {
  holdings: ApiHoldingRow[];
  summary: ApiPortfolioSummary;
}

interface ApiJournalEntry {
  id: number;
  trade_date: string;
  ticker: string;
  country: Country | null;
  bucket: Bucket | null;
  action: ActionType;
  suggested_price: number | null;
  actual_fill_price: number | null;
  qty: number | null;
  thesis: string | null;
  notes: string | null;
  lesson: string | null;
  skipped_month: boolean;
}

interface ApiSettingsBucketWeight {
  bucket: Bucket;
  allocation_pct: number;
}

interface ApiSettingsResponse {
  picks_per_bucket: number;
  bucket_allocations: ApiSettingsBucketWeight[];
  rebalance_day: number;
  telegram_enabled: boolean;
  email_enabled: boolean;
  stock_news_enabled: boolean;
  shock_detection_enabled: boolean;
  universe_nifty: string;
  universe_sp: string;
}

interface ApiRankedStock {
  ticker: string;
  country: Country;
  bucket: Bucket;
  rank: number;
  score: number;
  qualified: boolean;
  is_actionable: boolean;
  factor_scores: Record<string, number>;
  reason: string;
  company_name: string | null;
  sector: string | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  dividend_yield: number | null;
}

interface ApiBucketList {
  bucket: Bucket;
  country: Country;
  picks_per_bucket: number;
  ranked: ApiRankedStock[];
  extended: ApiRankedStock[];
}

interface ApiRankedResponse {
  lists: ApiBucketList[];
  run_date: string | null;
}

interface ApiNewsArticle {
  id: number;
  ticker: string | null;
  headline: string;
  source: string;
  url: string | null;
  published_at: string | null;
  sentiment: string | null;
  category: string | null;
}

interface ApiNewsFeedResponse {
  articles: ApiNewsArticle[];
  total: number;
}

interface ApiShockStatusResponse {
  active: boolean;
  current_event: {
    id: number;
    triggered_at: string;
    banner: ShockBanner;
    headline: string;
    dismissed_until: string | null;
  } | null;
}

interface ApiStockDetailResponse {
  ticker: string;
  country: Country;
  company_name: string | null;
  sector: string | null;
  description: string | null;
  market_cap: number | null;
  current_price: number | null;
  fundamentals: {
    roe: number | null;
    debt_equity: number | null;
    free_cash_flow: number | null;
    pe_ratio: number | null;
    pb_ratio: number | null;
    dividend_yield: number | null;
  } | null;
  sentiment: {
    positive_count: number;
    neutral_count: number;
    negative_count: number;
    avg_compound: number | null;
  } | null;
  forecasts: {
    analyst_count: number | null;
    buy_count: number | null;
    hold_count: number | null;
    sell_count: number | null;
    target_high: number | null;
    target_low: number | null;
    target_avg: number | null;
    current_price: number | null;
    consensus_rating: string | null;
    availability: string | null;
    note: string | null;
    quarterly_estimates: {
      period: string;
      fiscal_date: string | null;
      eps_estimate: number | null;
      revenue_estimate: number | null;
      analyst_count: number | null;
    }[];
  } | null;
  peers: {
    ticker: string;
    company_name: string | null;
    pe_ratio: number | null;
    roe: number | null;
    growth_rate: number | null;
    market_cap: number | null;
    bucket_membership: Bucket[];
  }[];
  peers_note: string | null;
  holding: {
    qty: number;
    avg_buy_price: number;
    buy_date: string | null;
    current_price: number | null;
    current_value: number | null;
    unrealized_pnl: number | null;
    unrealized_pnl_pct: number | null;
    days_held: number | null;
    ltcg_warning: boolean;
    pct_of_portfolio: number | null;
  } | null;
  events: { event_type: string; event_date: string | null; description: string | null }[];
  news: {
    id: number;
    headline: string;
    source: string;
    url: string | null;
    published_at: string | null;
    sentiment: string | null;
    category: string | null;
  }[];
  scores: {
    bucket: Bucket;
    score: number;
    qualified: boolean;
    rank: number | null;
    factor_scores: Record<string, number>;
    reason: string;
  }[];
  plain_english_reason: string;
  price_history: { date: string; close: number; volume: number | null }[];
}

// ---------------------------------------------------------------------------
// Adapters
// ---------------------------------------------------------------------------

function actionPriority(action: ActionType): number {
  const value = String(action).toLowerCase();
  if (value === "buy") return 0;
  if (value === "add") return 1;
  if (value === "sell") return 2;
  if (value === "trim") return 3;
  if (value === "hold") return 4;
  return 5;
}

function adaptActions(response: ApiActionsResponse): ActionsResponse {
  const rows = [...response.buys, ...response.adds, ...response.sells, ...response.holds].sort(
    (a, b) => {
      const byAction = actionPriority(a.action) - actionPriority(b.action);
      if (byAction !== 0) return byAction;
      const byBucket = a.bucket.localeCompare(b.bucket);
      if (byBucket !== 0) return byBucket;
      return (a.rank ?? 999) - (b.rank ?? 999);
    },
  );

  return {
    run_date: response.run_date,
    rows,
    shock_regime: response.shock_regime,
    macro_regime: response.macro_regime,
    plan: response.plan
      ? {
          fresh_capital: response.plan.fresh_capital,
          sell_proceeds: response.plan.sell_proceeds,
          total: response.plan.total_available,
          allocations: response.plan.bucket_allocations.map((allocation) => ({
            bucket: allocation.bucket,
            pct: allocation.pct,
            suggested_amount: allocation.amount,
          })),
          action_amounts: response.plan.action_amounts,
          undeployed: response.plan.undeployed,
        }
      : null,
  };
}

function adaptRankedStock(stock: ApiRankedStock): RankedStock {
  return {
    ticker: stock.ticker,
    name: stock.company_name ?? stock.ticker,
    sector: stock.sector,
    country: stock.country,
    score: stock.score,
    rank: stock.rank,
    is_actionable: stock.is_actionable,
    action: null,
    pe_ratio: stock.pe_ratio,
    pb_ratio: stock.pb_ratio,
    dividend_yield: stock.dividend_yield,
    market_cap: stock.market_cap,
    reason: stock.reason,
    bucket_flags: stock.qualified ? [stock.bucket] : [],
    sector_tilt: null,
  };
}

function adaptRanked(response: ApiRankedResponse): RankedResponse {
  return {
    run_date: response.run_date,
    lists: response.lists.map((list) => ({
      bucket: list.bucket,
      country: list.country,
      run_date: response.run_date,
      picks: list.picks_per_bucket,
      actionable: list.ranked.map(adaptRankedStock),
      extended: list.extended.map(adaptRankedStock),
      showing: list.ranked.length,
      total: list.ranked.length + list.extended.length,
    })),
  };
}

function adaptHolding(row: ApiHoldingRow): HoldingRow {
  return {
    id: row.id,
    ticker: row.ticker,
    name: row.name,
    sector: row.sector,
    country: row.country,
    qty: row.qty,
    avg_price: row.avg_buy_price,
    buy_date: row.buy_date,
    current_price: row.current_price,
    current_value: row.current_value,
    cost_basis: row.cost_basis,
    unrealized_pnl: row.unrealized_pnl,
    unrealized_pnl_pct: row.unrealized_pnl_pct,
    pct_of_portfolio: row.pct_of_portfolio,
    days_held: row.days_held,
    ltcg_warning: row.ltcg_warning,
    ltcg_status: row.ltcg_warning ? "LTCG_WARN" : null,
  };
}

function adaptPortfolio(response: ApiPortfolioResponse): PortfolioResponse {
  return {
    holdings: response.holdings.map(adaptHolding),
    summary: {
      total_value: response.summary.total_value,
      total_cost: response.summary.total_cost,
      total_pnl: response.summary.total_pnl,
      total_pnl_pct: response.summary.total_pnl_pct,
      india_value: response.summary.india_value,
      us_value: response.summary.us_value,
      india_pct: response.summary.india_pct,
      us_pct: response.summary.us_pct,
      sector_allocations: response.summary.sector_allocation,
      benchmarks: response.summary.benchmarks,
    },
  };
}

function adaptNews(response: ApiNewsFeedResponse): NewsFeedResponse {
  return {
    items: response.articles.map((article) => ({
      id: article.id,
      ticker: article.ticker,
      headline: article.headline,
      source: article.source,
      url: article.url,
      published_at: article.published_at ?? "",
      sentiment: (article.sentiment?.toLowerCase() as "positive" | "neutral" | "negative") ?? "neutral",
      category: article.category,
      stream: article.ticker ? "stock" : "general",
    })),
    total: response.total,
  };
}

function adaptShock(response: ApiShockStatusResponse): ShockBannerStatus {
  return {
    active: response.active,
    banner: response.current_event?.banner ?? null,
    headline: response.current_event?.headline ?? null,
    triggered_at: response.current_event?.triggered_at ?? null,
    dismissed_until: response.current_event?.dismissed_until ?? null,
  };
}

function adaptJournalEntry(entry: ApiJournalEntry): JournalEntry {
  return {
    id: entry.id,
    ticker: entry.ticker,
    country: entry.country,
    action_date: entry.trade_date,
    action_type: entry.action,
    bucket: entry.bucket,
    suggested_price: entry.suggested_price,
    fill_price: entry.actual_fill_price,
    qty: entry.qty,
    thesis: entry.thesis,
    notes: entry.notes,
    lesson: entry.lesson,
    skipped_month: entry.skipped_month,
  };
}

function adaptSettings(response: ApiSettingsResponse): SettingsResponse {
  const bucketAllocations: Record<Bucket, number> = {
    quality_value: 0,
    momentum: 0,
    quality_momentum: 0,
    dividend_growth: 0,
  };
  response.bucket_allocations.forEach((allocation) => {
    bucketAllocations[allocation.bucket] = allocation.allocation_pct;
  });

  return {
    picks_per_bucket: response.picks_per_bucket,
    rebalance_day: response.rebalance_day,
    universe_india: response.universe_nifty,
    universe_us: response.universe_sp,
    notify_telegram: response.telegram_enabled,
    notify_email: response.email_enabled,
    shock_detection: response.shock_detection_enabled,
    stock_news: response.stock_news_enabled,
    bucket_allocations: bucketAllocations,
    factor_weights: {},
  };
}

function adaptStock(response: ApiStockDetailResponse): StockDetailResponse {
  const week52High =
    response.price_history.length > 0
      ? Math.max(...response.price_history.map((point) => point.close))
      : null;
  const week52Low =
    response.price_history.length > 0
      ? Math.min(...response.price_history.map((point) => point.close))
      : null;

  return {
    ticker: response.ticker,
    name: response.company_name ?? response.ticker,
    country: response.country,
    sector: response.sector,
    market_cap: response.market_cap,
    current_price: response.current_price,
    week_52_high: week52High,
    week_52_low: week52Low,
    description: response.description,
    fundamentals: response.fundamentals
      ? {
          pe_ratio: response.fundamentals.pe_ratio,
          pb_ratio: response.fundamentals.pb_ratio,
          roe: response.fundamentals.roe,
          debt_equity: response.fundamentals.debt_equity,
          dividend_yield: response.fundamentals.dividend_yield,
          eps_growth_3y: null,
          fcf_positive:
            response.fundamentals.free_cash_flow != null
              ? response.fundamentals.free_cash_flow > 0
              : null,
        }
      : null,
    price_history: response.price_history.map((point) => ({
      date: point.date,
      open: point.close,
      high: point.close,
      low: point.close,
      close: point.close,
      volume: point.volume ?? 0,
    })),
    scores: response.scores.map((score) => ({
      bucket: score.bucket,
      score: score.score,
      factors: score.factor_scores,
      disqualified: !score.qualified,
    })),
    plain_english: response.plain_english_reason,
    news: response.news.map((item) => ({
      id: item.id,
      ticker: response.ticker,
      headline: item.headline,
      source: item.source,
      url: item.url,
      published_at: item.published_at ?? "",
      sentiment: (item.sentiment?.toLowerCase() as "positive" | "neutral" | "negative") ?? "neutral",
      category: item.category,
      stream: "stock",
    })),
    events: response.events.map((event) => ({
      event_type: event.event_type,
      event_date: event.event_date ?? "",
      description: event.description,
    })),
    forecasts: response.forecasts,
    peers: response.peers,
    peers_note: response.peers_note,
    holding: response.holding
      ? {
          id: 0,
          ticker: response.ticker,
          name: response.company_name ?? response.ticker,
          sector: response.sector,
          country: response.country,
          qty: response.holding.qty,
          avg_price: response.holding.avg_buy_price,
          buy_date: response.holding.buy_date ?? "",
          current_price: response.holding.current_price,
          current_value: response.holding.current_value,
          cost_basis: response.holding.qty * response.holding.avg_buy_price,
          unrealized_pnl: response.holding.unrealized_pnl,
          unrealized_pnl_pct: response.holding.unrealized_pnl_pct,
          pct_of_portfolio: response.holding.pct_of_portfolio,
          days_held: response.holding.days_held,
          ltcg_warning: response.holding.ltcg_warning,
          ltcg_status: response.holding.ltcg_warning ? "LTCG_WARN" : null,
        }
      : null,
    sentiment: response.sentiment
      ? {
          positive: response.sentiment.positive_count,
          neutral: response.sentiment.neutral_count,
          negative: response.sentiment.negative_count,
          trend:
            response.sentiment.avg_compound != null
              ? `Average compound sentiment: ${response.sentiment.avg_compound.toFixed(2)}`
              : null,
        }
      : null,
  };
}

function toSettingsPayload(settings: Partial<SettingsResponse>) {
  const bucketAllocations = settings.bucket_allocations
    ? (Object.entries(settings.bucket_allocations) as [Bucket, number][])
        .map(([bucket, allocation_pct]) => ({ bucket, allocation_pct }))
    : undefined;

  return {
    picks_per_bucket: settings.picks_per_bucket,
    rebalance_day: settings.rebalance_day,
    telegram_enabled: settings.notify_telegram,
    email_enabled: settings.notify_email,
    stock_news_enabled: settings.stock_news,
    shock_detection_enabled: settings.shock_detection,
    universe_nifty: settings.universe_india,
    universe_sp: settings.universe_us,
    bucket_allocations: bucketAllocations,
  };
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export const api = {
  dashboard: () => get<DashboardResponse>("/api/dashboard"),

  ranked: (params?: {
    bucket?: string;
    country?: string;
    sector?: string;
    pe_sort?: string;
    pb_sort?: string;
    picks?: number;
  }) => get<ApiRankedResponse>("/api/ranked", params).then(adaptRanked),

  actions: (params?: {
    fresh_capital?: number;
    sell_proceeds?: number;
    bucket_allocations?: Partial<Record<Bucket, number>>;
  }) =>
    get<ApiActionsResponse>("/api/actions", {
      fresh_capital: params?.fresh_capital,
      sell_proceeds: params?.sell_proceeds,
      bucket_alloc_quality_value: params?.bucket_allocations?.quality_value,
      bucket_alloc_momentum: params?.bucket_allocations?.momentum,
      bucket_alloc_quality_momentum: params?.bucket_allocations?.quality_momentum,
      bucket_alloc_dividend_growth: params?.bucket_allocations?.dividend_growth,
    }).then(adaptActions),

  executeAction: (
    ticker: string,
    body: {
      action: ActionType;
      bucket: Bucket;
      country: Country;
      qty: number;
      fill_price: number;
      notes?: string;
      lesson?: string;
    },
  ) =>
    post<{ id: number; ticker: string; status: string }>(`/api/actions/${ticker}/execute`, {
      action: body.action,
      bucket: body.bucket,
      country: body.country,
      qty: body.qty,
      actual_fill_price: body.fill_price,
      notes: body.notes,
      lesson: body.lesson,
    }),

  skipMonth: (body: { reason: string }) =>
    post<{ id: number; status: string; reason: string }>("/api/actions/skip-month", body),

  refreshPrices: () =>
    get<{ updated: Record<string, number>; as_of: string }>("/api/actions/refresh-prices").then(
      (response) => ({
        prices: response.updated,
        as_of: response.as_of,
      }),
    ),

  stock: (ticker: string) => get<ApiStockDetailResponse>(`/api/stocks/${ticker}`).then(adaptStock),

  portfolio: () => get<ApiPortfolioResponse>("/api/portfolio").then(adaptPortfolio),

  addHolding: (body: {
    ticker: string;
    country: Country;
    qty: number;
    avg_price: number;
    buy_date: string;
  }) =>
    post<ApiHoldingRow>("/api/portfolio/holdings", {
      ticker: body.ticker,
      country: body.country,
      qty: body.qty,
      avg_buy_price: body.avg_price,
      buy_date: body.buy_date,
    }).then(adaptHolding),

  updateHolding: (id: number, body: { qty?: number; avg_price?: number; buy_date?: string }) =>
    put<ApiHoldingRow>(`/api/portfolio/holdings/${id}`, {
      qty: body.qty,
      avg_buy_price: body.avg_price,
      buy_date: body.buy_date,
    }).then(adaptHolding),

  deleteHolding: (id: number) => del(`/api/portfolio/holdings/${id}`),

  news: (params?: {
    ticker?: string;
    category?: string;
    stream?: string;
    limit?: number;
    offset?: number;
  }) =>
    get<ApiNewsFeedResponse>("/api/news", {
      ...params,
      category: params?.category?.toLowerCase(),
    }).then(adaptNews),

  shock: () => get<ApiShockStatusResponse>("/api/shock").then(adaptShock),

  dismissShock: (id: number) =>
    post<{ id: number; dismissed_until: string }>(`/api/shock/${id}/dismiss`),

  journal: (params?: { limit?: number; offset?: number }) =>
    get<ApiJournalEntry[]>("/api/journal", params).then((entries) => entries.map(adaptJournalEntry)),

  createJournal: (body: {
    trade_date: string;
    ticker: string;
    country: Country;
    action: ActionType;
    bucket?: Bucket | null;
    suggested_price?: number;
    fill_price?: number;
    qty?: number;
    thesis?: string;
    notes?: string;
    lesson?: string;
  }) =>
    post<ApiJournalEntry>("/api/journal", {
      trade_date: body.trade_date,
      ticker: body.ticker,
      country: body.country,
      action: body.action,
      bucket: body.bucket,
      suggested_price: body.suggested_price,
      actual_fill_price: body.fill_price,
      qty: body.qty,
      thesis: body.thesis,
      notes: body.notes,
      lesson: body.lesson,
    }).then(adaptJournalEntry),

  updateJournal: (
    id: number,
    body: { fill_price?: number; qty?: number; notes?: string; lesson?: string },
  ) =>
    put<ApiJournalEntry>(`/api/journal/${id}`, {
      actual_fill_price: body.fill_price,
      qty: body.qty,
      notes: body.notes,
      lesson: body.lesson,
    }).then(adaptJournalEntry),

  journalReview: (months?: number) =>
    get<MonthlyReview[]>("/api/journal/review", months ? { months } : undefined),

  settings: () => get<ApiSettingsResponse>("/api/settings").then(adaptSettings),

  saveSettings: (body: Partial<SettingsResponse>) =>
    put<ApiSettingsResponse>("/api/settings", toSettingsPayload(body)).then(adaptSettings),

  runPipeline: () => post<{ status: string; message: string }>("/api/pipeline/run"),
};

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, StockDetailResponse } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  bucketColor,
  bucketLabel,
  countryFlag,
  fmtCompactNum,
  fmtDate,
  fmtINR,
  fmtNum,
  fmtPct,
  fmtUSD,
  sentimentColor,
} from "@/lib/format";
import {
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function StockDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [stock, setStock] = useState<StockDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    console.log(`[Stock/${ticker}] fetching`);
    api
      .stock(ticker)
      .then((response) => {
        console.log(`[Stock/${ticker}] received:`, response);
        setStock(response);
      })
      .catch((err) => console.error(`[Stock/${ticker}] fetch error:`, err))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) {
    return (
      <div className="mx-auto flex max-w-6xl flex-col gap-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-2">
            <div className="h-8 w-32 rounded skeleton-shimmer" />
            <div className="h-4 w-56 rounded skeleton-shimmer" />
            <div className="h-5 w-80 rounded skeleton-shimmer" />
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="h-8 w-28 rounded skeleton-shimmer" />
            <div className="h-4 w-40 rounded skeleton-shimmer" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Card key={index}>
              <CardContent className="flex flex-col gap-2 py-3">
                <div className="h-3 w-16 rounded skeleton-shimmer" />
                <div className="h-5 w-20 rounded skeleton-shimmer" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (!stock) {
    return <p className="text-sm text-muted-foreground">Stock not found.</p>;
  }

  const isIndia = stock.country === "IN";
  const fund = stock.fundamentals;
  const quote = stock.latest_quote;
  const guardrails = stock.india_guardrails;
  const hasHardGuardrail =
    Boolean(guardrails?.in_fno_ban) ||
    Boolean(guardrails?.in_asm_gsm) ||
    (guardrails?.promoter_pledge_pct ?? 0) > 50;
  const hasPledgeCaution =
    !hasHardGuardrail &&
    (guardrails?.promoter_pledge_pct ?? 0) > 25 &&
    (guardrails?.promoter_pledge_pct ?? 0) <= 50;
  const tabItems = [
    { value: "overview", label: "Overview" },
    ...(isIndia ? [{ value: "india", label: "India Signals" }] : []),
    { value: "score", label: "Score" },
    { value: "chart", label: "Chart" },
    { value: "news", label: "News" },
    { value: "events", label: "Events" },
    { value: "holding", label: "Holding" },
    { value: "sentiment", label: "Sentiment" },
    { value: "forecasts", label: "Forecasts" },
    { value: "peers", label: "Peers" },
  ];

  const overviewCards = [
    { label: "P/E Ratio", value: fmtNum(fund?.pe_ratio, 1) },
    { label: "P/B Ratio", value: fmtNum(fund?.pb_ratio, 1) },
    { label: "ROE", value: formatPercent(fund?.roe, 1) },
    { label: "ROCE", value: formatPercent(fund?.roce, 1) },
    { label: "D/E Ratio", value: fmtNum(fund?.debt_equity, 2) },
    { label: "Div Yield", value: formatPercent(fund?.dividend_yield, 2) },
    { label: "FCF", value: stock.fundamentals?.free_cash_flow != null ? formatMoney(stock.country, stock.fundamentals.free_cash_flow) : "—" },
    { label: "Market Cap", value: formatMoney(stock.country, stock.market_cap) },
  ];

  if (isIndia) {
    overviewCards.push(
      { label: "VWAP", value: fmtNum(quote?.vwap, 2) },
      { label: "Delivery %", value: formatPercent(quote?.delivery_pct, 1) },
      { label: "Delivery Vol", value: fmtCompactNum(quote?.delivery_volume) },
      { label: "Promoter Pledge", value: formatPercent(fund?.promoter_pledge_pct, 1) },
      { label: "FII Holding", value: formatPercent(fund?.fii_holding, 1) },
      { label: "DII Holding", value: formatPercent(fund?.dii_holding, 1) },
      {
        label: "Statement",
        value:
          fund?.is_consolidated == null
            ? "—"
            : fund.is_consolidated
              ? "Consolidated"
              : "Standalone",
      },
      { label: "Data Source", value: formatSource(fund?.data_source) },
    );
  }

  const ownershipCards = [
    { label: "Promoter Holding", value: formatPercent(fund?.promoter_holding, 1) },
    { label: "Promoter Pledge", value: formatPercent(fund?.promoter_pledge_pct, 1) },
    { label: "FII Holding", value: formatPercent(fund?.fii_holding, 1) },
    { label: "DII Holding", value: formatPercent(fund?.dii_holding, 1) },
    { label: "Statement Type", value: fund?.is_consolidated == null ? "—" : fund.is_consolidated ? "Consolidated" : "Standalone" },
    { label: "Latest Quarter", value: fmtDate(fund?.as_of) },
  ];

  const bankCards = [
    { label: "GNPA", value: formatPercent(fund?.gnpa_pct, 2) },
    { label: "NNPA", value: formatPercent(fund?.nnpa_pct, 2) },
    { label: "NIM", value: formatPercent(fund?.nim_pct, 2) },
    { label: "CASA Ratio", value: formatPercent(fund?.casa_ratio, 2) },
    { label: "Credit Cost", value: formatPercent(fund?.credit_cost, 2) },
    { label: "Capital Adequacy", value: formatPercent(fund?.capital_adequacy_ratio, 2) },
  ].filter((item) => item.value !== "—");

  const derivativeCards = stock.derivatives
    ? [
        { label: "PCR", value: fmtNum(stock.derivatives.put_call_ratio, 2) },
        { label: "Max Pain", value: fmtNum(stock.derivatives.max_pain_strike, 0) },
        { label: "ATM IV", value: formatPercent(stock.derivatives.atm_iv, 1) },
        { label: "Futures OI", value: fmtCompactNum(stock.derivatives.oi_futures) },
        { label: "OI Change", value: fmtCompactNum(stock.derivatives.oi_futures_change) },
        { label: "Call OI", value: fmtCompactNum(stock.derivatives.oi_call_total) },
        { label: "Put OI", value: fmtCompactNum(stock.derivatives.oi_put_total) },
        { label: "Top Call Strike", value: fmtNum(stock.derivatives.top_call_oi_strike, 0) },
        { label: "Top Put Strike", value: fmtNum(stock.derivatives.top_put_oi_strike, 0) },
      ]
    : [];

  const indiaSignalsAvailable =
    Boolean(quote?.vwap != null || quote?.delivery_pct != null) ||
    Boolean(stock.derivatives) ||
    Boolean(stock.market_depth) ||
    stock.recent_bulk_deals.length > 0 ||
    stock.recent_insider_trades.length > 0 ||
    ownershipCards.some((item) => item.value !== "—") ||
    bankCards.length > 0;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4 animate-fade-in-up">
        <div className="flex flex-col gap-2">
          <div>
            <h1 className="flex items-center gap-2 font-mono text-2xl font-bold text-foreground">
              {stock.ticker}
              <span className="text-base font-normal text-muted-foreground">
                {countryFlag(stock.country)}
              </span>
            </h1>
            <p className="text-sm text-muted-foreground">{stock.name}</p>
            {stock.sector && (
              <p className="text-xs text-muted-foreground/70">{stock.sector}</p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {stock.nse_symbol && (
              <Badge variant="outline">NSE {stock.nse_symbol}</Badge>
            )}
            {stock.bse_symbol && (
              <Badge variant="outline">BSE {stock.bse_symbol}</Badge>
            )}
            {stock.bse_scripcode && (
              <Badge variant="outline">Scrip {stock.bse_scripcode}</Badge>
            )}
            {stock.isin && (
              <Badge variant="outline">ISIN {stock.isin}</Badge>
            )}
            {fund?.data_source && (
              <Badge variant="secondary">{formatSource(fund.data_source)}</Badge>
            )}
            {fund?.is_consolidated != null && (
              <Badge variant="secondary">
                {fund.is_consolidated ? "Consolidated" : "Standalone"}
              </Badge>
            )}
            {guardrails?.in_fno_ban && (
              <Badge variant="destructive">F&O Ban</Badge>
            )}
            {guardrails?.in_asm_gsm && (
              <Badge variant="destructive">ASM/GSM</Badge>
            )}
            {hasPledgeCaution && (
              <Badge variant="secondary">High Pledge</Badge>
            )}
          </div>
        </div>

        <div className="text-right">
          <p className="text-2xl font-semibold text-foreground">
            {formatMoney(stock.country, stock.current_price)}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            52w: {fmtNum(stock.week_52_low, 1)} - {fmtNum(stock.week_52_high, 1)}
          </p>
          {isIndia && (quote?.vwap != null || quote?.delivery_pct != null) && (
            <p className="mt-1 text-xs text-muted-foreground">
              VWAP {fmtNum(quote?.vwap, 2)} · Delivery {formatPercent(quote?.delivery_pct, 1)}
            </p>
          )}
        </div>
      </div>

      {stock.scores.filter((score) => !score.disqualified && score.score > 0).length > 0 && (
        <div className="flex flex-wrap gap-2 animate-fade-in-up">
          {stock.scores
            .filter((score) => !score.disqualified && score.score > 0)
            .map((score) => (
              <span
                key={score.bucket}
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium text-white ${bucketColor(score.bucket)}`}
              >
                {bucketLabel(score.bucket)} · {fmtNum(score.score, 0)}
              </span>
            ))}
        </div>
      )}

      {stock.plain_english && (
        <Card className="bg-primary/5 ring-primary/20 animate-fade-in-up">
          <CardContent className="py-3 text-sm text-foreground/85">
            {stock.plain_english}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="h-auto w-full justify-start gap-0 overflow-x-auto rounded-none border-b border-border bg-card p-0">
          {tabItems.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className="shrink-0 rounded-none border-b-2 border-transparent px-4 py-2.5 text-xs text-muted-foreground transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary"
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {overviewCards.map((item, index) => (
              <MetricCard
                key={`${item.label}-${index}`}
                label={item.label}
                value={item.value}
              />
            ))}
          </div>

          {stock.description && (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle>About</CardTitle>
              </CardHeader>
              <CardContent className="text-sm leading-relaxed text-muted-foreground">
                {stock.description}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {isIndia && (
          <TabsContent value="india" className="mt-4">
            {!indiaSignalsAvailable ? (
              <p className="text-sm text-muted-foreground">
                No India-specific signal data has been synced for this stock yet.
              </p>
            ) : (
              <div className="flex flex-col gap-4">
                {guardrails && (
                  <Alert variant={hasHardGuardrail ? "destructive" : "default"}>
                    <AlertTitle>Investability Flags</AlertTitle>
                    <AlertDescription>
                      {guardrailMessage(guardrails)}
                    </AlertDescription>
                  </Alert>
                )}

                <Card>
                  <CardHeader>
                    <CardTitle>Ownership And Statement Quality</CardTitle>
                    <CardDescription>
                      Latest official-source shareholding and statement metadata.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-3">
                    {ownershipCards.map((item, index) => (
                      <MetricCard
                        key={`${item.label}-${index}`}
                        label={item.label}
                        value={item.value}
                        compact
                      />
                    ))}
                  </CardContent>
                </Card>

                {bankCards.length > 0 && (
                  <Card>
                    <CardHeader>
                      <CardTitle>Bank And NBFC Metrics</CardTitle>
                      <CardDescription>
                        Sector-specific ratios surfaced from the India fundamentals lane.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-3">
                      {bankCards.map((item, index) => (
                        <MetricCard
                          key={`${item.label}-${index}`}
                          label={item.label}
                          value={item.value}
                          compact
                        />
                      ))}
                    </CardContent>
                  </Card>
                )}

                {stock.derivatives && (
                  <Card>
                    <CardHeader>
                      <CardTitle>Derivatives Sentiment</CardTitle>
                      <CardDescription>
                        Option-chain and F&O positioning for {fmtDate(stock.derivatives.as_of)}.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-3">
                      {derivativeCards.map((item, index) => (
                        <MetricCard
                          key={`${item.label}-${index}`}
                          label={item.label}
                          value={item.value}
                          compact
                        />
                      ))}
                    </CardContent>
                  </Card>
                )}

                <Card>
                  <CardHeader>
                    <CardTitle>Market Depth</CardTitle>
                    <CardDescription>
                      {stock.market_depth
                        ? `Latest top-of-book snapshot from ${formatSource(stock.market_depth.source)} on ${fmtDate(stock.market_depth.snapshot_at)}.`
                        : "No recent market depth snapshot is stored for this stock."}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {stock.market_depth ? (
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="flex flex-col gap-3">
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span>Buy depth</span>
                            <span>Total qty {fmtCompactNum(stock.market_depth.total_buy_qty)}</span>
                          </div>
                          <DepthTable levels={stock.market_depth.buy_depth} />
                        </div>
                        <div className="flex flex-col gap-3">
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span>Sell depth</span>
                            <span>Total qty {fmtCompactNum(stock.market_depth.total_sell_qty)}</span>
                          </div>
                          <DepthTable levels={stock.market_depth.sell_depth} />
                        </div>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">
                        Market depth is only captured when the India sync has a live official snapshot available.
                      </p>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Bulk And Block Deals</CardTitle>
                    <CardDescription>
                      Recent high-signal institutional disclosures from NSE and BSE.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {stock.recent_bulk_deals.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No recent bulk or block deals were stored for this stock.
                      </p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Date</TableHead>
                            <TableHead>Type</TableHead>
                            <TableHead>Client</TableHead>
                            <TableHead>Side</TableHead>
                            <TableHead className="text-right">Qty</TableHead>
                            <TableHead className="text-right">Price</TableHead>
                            <TableHead>Source</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {stock.recent_bulk_deals.map((deal, index) => (
                            <TableRow key={`${deal.trade_date}-${deal.client_name ?? "client"}-${index}`}>
                              <TableCell>{fmtDate(deal.trade_date)}</TableCell>
                              <TableCell className="capitalize">{deal.deal_type}</TableCell>
                              <TableCell className="max-w-56 truncate">{deal.client_name ?? "—"}</TableCell>
                              <TableCell>{deal.transaction_type ?? "—"}</TableCell>
                              <TableCell className="text-right">{fmtCompactNum(deal.quantity)}</TableCell>
                              <TableCell className="text-right">{fmtNum(deal.trade_price, 2)}</TableCell>
                              <TableCell>{formatSource(deal.source)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Insider Trading Disclosures</CardTitle>
                    <CardDescription>
                      Promoter and insider transactions carried into the India disclosure layer.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {stock.recent_insider_trades.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No recent insider trade disclosures were stored for this stock.
                      </p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Date</TableHead>
                            <TableHead>Person</TableHead>
                            <TableHead>Category</TableHead>
                            <TableHead>Type</TableHead>
                            <TableHead className="text-right">Shares</TableHead>
                            <TableHead className="text-right">Price</TableHead>
                            <TableHead className="text-right">Post %</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {stock.recent_insider_trades.map((trade, index) => (
                            <TableRow key={`${trade.person_name ?? "person"}-${trade.trade_date ?? trade.to_date ?? index}`}>
                              <TableCell>{fmtDate(trade.trade_date ?? trade.to_date ?? trade.from_date)}</TableCell>
                              <TableCell className="max-w-48 truncate">{trade.person_name ?? "—"}</TableCell>
                              <TableCell>{trade.person_category ?? "—"}</TableCell>
                              <TableCell>{trade.transaction_type ?? "—"}</TableCell>
                              <TableCell className="text-right">{fmtCompactNum(trade.shares_traded)}</TableCell>
                              <TableCell className="text-right">{fmtNum(trade.trade_price, 2)}</TableCell>
                              <TableCell className="text-right">{formatPercent(trade.post_trade_pct, 2)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </CardContent>
                </Card>
              </div>
            )}
          </TabsContent>
        )}

        <TabsContent value="score" className="mt-4">
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Score Radar</CardTitle>
                <CardDescription>Bucket-level profile for this stock.</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <RadarChart
                    data={stock.scores.map((score) => ({
                      name: bucketLabel(score.bucket).split(" ")[0],
                      score: score.score,
                    }))}
                  >
                    <PolarGrid stroke="var(--border)" />
                    <PolarAngleAxis
                      dataKey="name"
                      tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                    />
                    <Radar dataKey="score" stroke="#9FE870" fill="#9FE870" fillOpacity={0.2} />
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <div className="flex flex-col gap-3">
              {stock.scores.map((score) => (
                <Card key={score.bucket}>
                  <CardContent className="flex flex-col gap-2 py-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-foreground/85">
                        {bucketLabel(score.bucket)}
                      </span>
                      <span
                        className={`font-mono text-xs ${
                          score.disqualified ? "text-negative" : "text-foreground"
                        }`}
                      >
                        {score.disqualified ? "DQ" : fmtNum(score.score, 0)}
                      </span>
                    </div>
                    <div className="flex flex-col gap-1">
                      {Object.entries(score.factors).map(([factor, points]) => (
                        <div key={factor} className="flex items-center gap-2">
                          <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-primary transition-all duration-500"
                              style={{ width: `${Math.min(100, (points / 25) * 100)}%` }}
                            />
                          </div>
                          <span className="w-24 truncate text-xs text-muted-foreground">
                            {factor}
                          </span>
                          <span className="w-6 text-right font-mono text-xs text-foreground/70">
                            {points}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="chart" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Price History</CardTitle>
              <CardDescription>Last 12 months of stored close prices.</CardDescription>
            </CardHeader>
            <CardContent>
              {stock.price_history.length === 0 ? (
                <p className="text-sm text-muted-foreground">No price data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={stock.price_history}>
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                      tickFormatter={(value) => String(value).slice(5)}
                    />
                    <YAxis
                      tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                      width={72}
                      tickFormatter={(value) => Number(value).toFixed(0)}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "var(--card)",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        color: "var(--foreground)",
                      }}
                      labelStyle={{ color: "var(--muted-foreground)", fontSize: 11 }}
                      itemStyle={{ color: "var(--foreground)", fontSize: 11 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="close"
                      stroke="#9FE870"
                      strokeWidth={1.5}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="news" className="mt-4">
          <div className="flex flex-col gap-2">
            {stock.news.length === 0 ? (
              <p className="text-sm text-muted-foreground">No recent news.</p>
            ) : (
              stock.news.map((item) => (
                <div
                  key={item.id}
                  className="flex items-start gap-3 rounded-sm border-b border-border py-2.5 transition-colors duration-150 hover:bg-accent/30 last:border-0"
                >
                  <span
                    className={`mt-0.5 shrink-0 text-xs font-medium ${sentimentColor(item.sentiment)}`}
                  >
                    {item.sentiment === "positive" ? "+" : item.sentiment === "negative" ? "-" : "·"}
                  </span>
                  <div className="min-w-0 flex-1">
                    {item.url ? (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="line-clamp-2 text-sm text-foreground transition-colors hover:text-primary"
                      >
                        {item.headline}
                      </a>
                    ) : (
                      <p className="line-clamp-2 text-sm text-foreground">{item.headline}</p>
                    )}
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {item.source} · {fmtDate(item.published_at)}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </TabsContent>

        <TabsContent value="events" className="mt-4">
          <div className="flex flex-col gap-2">
            {stock.events.length === 0 ? (
              <p className="text-sm text-muted-foreground">No upcoming events.</p>
            ) : (
              stock.events.map((event, index) => (
                <div
                  key={`${event.event_type}-${event.event_date}-${index}`}
                  className="flex flex-wrap items-center gap-3 rounded-sm border-b border-border py-2 last:border-0 transition-colors duration-150 hover:bg-accent/30"
                >
                  <span className="w-28 shrink-0 font-mono text-xs text-foreground/80">
                    {fmtDate(event.event_date)}
                  </span>
                  <Badge variant="outline">{event.event_type}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {event.description ?? ""}
                  </span>
                </div>
              ))
            )}
          </div>
        </TabsContent>

        <TabsContent value="holding" className="mt-4">
          {stock.holding ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              {[
                { label: "Quantity", value: fmtNum(stock.holding.qty, 2) },
                { label: "Avg Buy Price", value: formatMoney(stock.country, stock.holding.avg_price) },
                { label: "Current Value", value: formatMoney(stock.country, stock.holding.current_value) },
                { label: "Unrealized P&L", value: formatMoney(stock.country, stock.holding.unrealized_pnl) },
                { label: "P&L %", value: fmtPct(stock.holding.unrealized_pnl_pct) },
                { label: "Days Held", value: stock.holding.days_held != null ? String(stock.holding.days_held) : "—" },
                { label: "% of Portfolio", value: formatPercent(stock.holding.pct_of_portfolio, 1) },
                { label: "Tax Status", value: stock.holding.ltcg_status ?? "—" },
                { label: "Buy Date", value: fmtDate(stock.holding.buy_date) },
              ].map((item, index) => (
                <MetricCard key={`${item.label}-${index}`} label={item.label} value={item.value} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">You do not hold this stock.</p>
          )}
        </TabsContent>

        <TabsContent value="sentiment" className="mt-4">
          {stock.sentiment ? (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-3 gap-4">
                <MetricCard label="Positive" value={String(stock.sentiment.positive)} tone="positive" />
                <MetricCard label="Neutral" value={String(stock.sentiment.neutral)} />
                <MetricCard label="Negative" value={String(stock.sentiment.negative)} tone="negative" />
              </div>
              {stock.sentiment.trend && (
                <p className="text-sm text-muted-foreground">{stock.sentiment.trend}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No sentiment data.</p>
          )}
        </TabsContent>

        <TabsContent value="forecasts" className="mt-4">
          {stock.forecasts ? (
            <div className="flex flex-col gap-4">
              {stock.forecasts.note && (
                <Card className="bg-warning/10 ring-warning/30">
                  <CardContent className="py-3 text-sm text-warning">
                    {stock.forecasts.note}
                  </CardContent>
                </Card>
              )}

              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {[
                  { label: "Analysts", value: stock.forecasts.analyst_count != null ? String(stock.forecasts.analyst_count) : "—" },
                  { label: "Buy", value: stock.forecasts.buy_count != null ? String(stock.forecasts.buy_count) : "—" },
                  { label: "Hold", value: stock.forecasts.hold_count != null ? String(stock.forecasts.hold_count) : "—" },
                  { label: "Sell", value: stock.forecasts.sell_count != null ? String(stock.forecasts.sell_count) : "—" },
                  { label: "Target High", value: formatMoney(stock.country, stock.forecasts.target_high) },
                  { label: "Target Avg", value: formatMoney(stock.country, stock.forecasts.target_avg) },
                  { label: "Target Low", value: formatMoney(stock.country, stock.forecasts.target_low) },
                  { label: "Current Price", value: formatMoney(stock.country, stock.forecasts.current_price) },
                  { label: "Consensus", value: stock.forecasts.consensus_rating ?? "—" },
                  { label: "Source", value: stock.forecasts.availability ?? "—" },
                ].map((item, index) => (
                  <MetricCard key={`${item.label}-${index}`} label={item.label} value={item.value} />
                ))}
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Quarterly Estimates</CardTitle>
                  <CardDescription>Next available EPS and revenue estimates.</CardDescription>
                </CardHeader>
                <CardContent>
                  {stock.forecasts.quarterly_estimates.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No forward estimates were returned for this stock.
                    </p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Period</TableHead>
                          <TableHead>Fiscal Date</TableHead>
                          <TableHead className="text-right">EPS</TableHead>
                          <TableHead className="text-right">Revenue</TableHead>
                          <TableHead className="text-right">Analysts</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {stock.forecasts.quarterly_estimates.map((estimate) => (
                          <TableRow key={`${estimate.period}-${estimate.fiscal_date ?? "na"}`}>
                            <TableCell>{estimate.period}</TableCell>
                            <TableCell>{fmtDate(estimate.fiscal_date)}</TableCell>
                            <TableCell className="text-right">{fmtNum(estimate.eps_estimate, 2)}</TableCell>
                            <TableCell className="text-right">{fmtCompactNum(estimate.revenue_estimate)}</TableCell>
                            <TableCell className="text-right">
                              {estimate.analyst_count != null ? String(estimate.analyst_count) : "—"}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No analyst forecast data stored for this stock yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="peers" className="mt-4">
          {stock.peers.length === 0 ? (
            <p className="text-sm text-muted-foreground">No peer comparison available yet.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {stock.peers_note && (
                <Card className="bg-muted/30">
                  <CardContent className="py-3 text-sm text-muted-foreground">
                    {stock.peers_note}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardContent className="pt-0">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Ticker</TableHead>
                        <TableHead className="text-right">P/E</TableHead>
                        <TableHead className="text-right">ROE</TableHead>
                        <TableHead className="text-right">Growth</TableHead>
                        <TableHead className="text-right">Market Cap</TableHead>
                        <TableHead>Buckets</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {stock.peers.map((peer) => (
                        <TableRow key={peer.ticker}>
                          <TableCell>
                            <a
                              href={`/stocks/${peer.ticker}`}
                              className="font-mono font-medium text-primary transition-colors hover:text-primary/80"
                            >
                              {peer.ticker}
                            </a>
                            {peer.company_name && (
                              <span className="ml-2 text-muted-foreground">{peer.company_name}</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">{fmtNum(peer.pe_ratio, 1)}</TableCell>
                          <TableCell className="text-right">{formatPercent(peer.roe, 1)}</TableCell>
                          <TableCell className="text-right">{formatPercent(peer.growth_rate, 1)}</TableCell>
                          <TableCell className="text-right">
                            {formatMoney(stock.country, peer.market_cap)}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {peer.bucket_membership.length > 0 ? (
                                peer.bucket_membership.map((bucket) => (
                                  <Badge
                                    key={`${peer.ticker}-${bucket}`}
                                    variant="outline"
                                  >
                                    {bucketLabel(bucket)}
                                  </Badge>
                                ))
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function MetricCard({
  label,
  value,
  compact = false,
  tone = "default",
}: {
  label: string;
  value: string;
  compact?: boolean;
  tone?: "default" | "positive" | "negative";
}) {
  return (
    <Card size={compact ? "sm" : "default"}>
      <CardContent className="flex flex-col gap-1 py-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p
          className={`font-mono ${compact ? "text-base" : "text-lg"} ${
            tone === "positive"
              ? "text-positive"
              : tone === "negative"
                ? "text-negative"
                : "text-foreground"
          }`}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

function DepthTable({
  levels,
}: {
  levels: { price: number; quantity: number; orders: number | null }[];
}) {
  if (levels.length === 0) {
    return <p className="text-sm text-muted-foreground">No depth levels captured.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-right">Price</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">Orders</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {levels.map((level, index) => (
          <TableRow key={`${level.price}-${index}`}>
            <TableCell className="text-right">{fmtNum(level.price, 2)}</TableCell>
            <TableCell className="text-right">{fmtCompactNum(level.quantity)}</TableCell>
            <TableCell className="text-right">
              {level.orders != null ? String(level.orders) : "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function formatMoney(country: "IN" | "US", value: number | null | undefined): string {
  return country === "IN" ? fmtINR(value) : fmtUSD(value);
}

function formatPercent(value: number | null | undefined, decimals = 1): string {
  return value == null ? "—" : `${fmtNum(value, decimals)}%`;
}

function formatSource(value: string | null | undefined): string {
  return value ? value.replaceAll("_", " ").toUpperCase() : "—";
}

function guardrailMessage(guardrails: {
  in_fno_ban: boolean;
  in_asm_gsm: boolean;
  promoter_pledge_pct: number | null;
}): string {
  const parts: string[] = [];
  if (guardrails.in_fno_ban) parts.push("currently in the NSE F&O ban list");
  if (guardrails.in_asm_gsm) parts.push("on ASM/GSM surveillance");
  if ((guardrails.promoter_pledge_pct ?? 0) > 50) {
    parts.push(`promoter pledge is ${fmtNum(guardrails.promoter_pledge_pct, 1)}%`);
  } else if ((guardrails.promoter_pledge_pct ?? 0) > 25) {
    parts.push(`promoter pledge is elevated at ${fmtNum(guardrails.promoter_pledge_pct, 1)}%`);
  }
  return parts.length > 0
    ? `This stock is ${parts.join(", ")}.`
    : "No active India-specific guardrail disqualifiers are currently stored for this stock.";
}

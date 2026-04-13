"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, StockDetailResponse } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fmtNum,
  fmtPct,
  fmtDate,
  fmtINR,
  bucketLabel,
  bucketColor,
  sentimentColor,
  countryFlag,
} from "@/lib/format";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
} from "recharts";

export default function StockDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [stock, setStock] = useState<StockDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (ticker) {
      console.log(`[Stock/${ticker}] fetching`);
      api
        .stock(ticker)
        .then((s) => {
          console.log(`[Stock/${ticker}] received:`, s);
          console.log(`[Stock/${ticker}] price=${s.current_price} fundamentals=${s.fundamentals ? "yes" : "null"} scores=${s.scores.length} price_history=${s.price_history.length}`);
          setStock(s);
        })
        .catch((err) => console.error(`[Stock/${ticker}] fetch error:`, err))
        .finally(() => setLoading(false));
    }
  }, [ticker]);

  if (loading) {
    return (
      <div className="space-y-4 max-w-4xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="h-8 w-32 skeleton-shimmer rounded" />
            <div className="h-4 w-48 skeleton-shimmer rounded mt-2" />
          </div>
          <div className="h-8 w-24 skeleton-shimmer rounded" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} className="bg-card border-border">
              <CardContent className="px-4 py-3">
                <div className="h-3 w-16 skeleton-shimmer rounded mb-2" />
                <div className="h-5 w-20 skeleton-shimmer rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (!stock) return <p className="text-muted-foreground text-sm">Stock not found.</p>;

  const fund = stock.fundamentals;

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap animate-fade-in-up">
        <div>
          <h1 className="text-2xl font-bold text-foreground font-mono flex items-center gap-2">
            {stock.ticker}
            <span className="text-base text-muted-foreground font-normal">{countryFlag(stock.country)}</span>
          </h1>
          <p className="text-muted-foreground text-sm">{stock.name}</p>
          {stock.sector && (
            <p className="text-muted-foreground/60 text-xs mt-0.5">{stock.sector}</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-2xl font-mono font-semibold text-foreground">
            {stock.current_price != null ? fmtNum(stock.current_price, 2) : "—"}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            52w: {fmtNum(stock.week_52_low, 1)} – {fmtNum(stock.week_52_high, 1)}
          </p>
        </div>
      </div>

      {/* Bucket badges */}
      {stock.scores.filter((s) => !s.disqualified && s.score > 0).length > 0 && (
        <div className="flex items-center gap-2 flex-wrap animate-fade-in-up stagger-2">
          {stock.scores
            .filter((s) => !s.disqualified && s.score > 0)
            .map((s) => (
              <span
                key={s.bucket}
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium text-white ${bucketColor(s.bucket)}`}
              >
                {bucketLabel(s.bucket)} · {fmtNum(s.score, 0)}
              </span>
            ))}
        </div>
      )}

      {/* Plain-English explanation */}
      {stock.plain_english && (
        <Card className="bg-primary/5 border-primary/20 animate-fade-in-up stagger-3">
          <CardContent className="px-4 py-3 text-sm text-foreground/80">
            {stock.plain_english}
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="bg-card border-b border-border rounded-none h-auto p-0 w-full justify-start gap-0 overflow-x-auto">
          {["overview", "score", "chart", "news", "events", "holding", "sentiment", "forecasts", "peers"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary text-muted-foreground text-xs px-4 py-2.5 capitalize cursor-pointer transition-colors shrink-0"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Overview */}
        <TabsContent value="overview" className="mt-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "P/E Ratio", value: fmtNum(fund?.pe_ratio, 1) },
              { label: "P/B Ratio", value: fmtNum(fund?.pb_ratio, 1) },
              { label: "ROE", value: fund?.roe != null ? `${fmtNum(fund.roe, 1)}%` : "—" },
              { label: "D/E Ratio", value: fmtNum(fund?.debt_equity, 2) },
              { label: "Div Yield", value: fund?.dividend_yield != null ? `${fmtNum(fund.dividend_yield, 2)}%` : "—" },
              { label: "EPS Growth 3Y", value: fund?.eps_growth_3y != null ? `${fmtNum(fund.eps_growth_3y, 1)}%` : "—" },
              { label: "FCF Positive", value: fund?.fcf_positive != null ? (fund.fcf_positive ? "Yes" : "No") : "—" },
              { label: "Market Cap", value: stock.market_cap != null ? (stock.country === "IN" ? fmtINR(stock.market_cap) : `$${(stock.market_cap / 1e9).toFixed(1)}B`) : "—" },
            ].map(({ label, value }, i) => (
              <Card key={label} className="bg-card border-border card-hover animate-fade-in-up" style={{ animationDelay: `${i * 50}ms` }}>
                <CardContent className="px-4 py-3">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="text-lg font-mono text-foreground mt-0.5">{value}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          {stock.description && (
            <p className="text-sm text-muted-foreground mt-4 leading-relaxed">{stock.description}</p>
          )}
        </TabsContent>

        {/* Score breakdown */}
        <TabsContent value="score" className="mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Radar */}
            <Card className="bg-card border-border">
              <CardHeader className="px-4 pt-4 pb-2">
                <CardTitle className="text-xs text-muted-foreground font-normal">Score Radar</CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <ResponsiveContainer width="100%" height={220}>
                  <RadarChart data={stock.scores.map((s) => ({ name: bucketLabel(s.bucket).split(" ")[0], score: s.score }))}>
                    <PolarGrid stroke="var(--border)" />
                    <PolarAngleAxis dataKey="name" tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} />
                    <Radar dataKey="score" stroke="#9FE870" fill="#9FE870" fillOpacity={0.2} />
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Factor breakdown per bucket */}
            <div className="space-y-3">
              {stock.scores.map((s) => (
                <Card key={s.bucket} className="bg-card border-border">
                  <CardContent className="px-4 py-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-foreground/80">{bucketLabel(s.bucket)}</span>
                      <span className={`text-xs font-mono ${s.disqualified ? "text-negative" : "text-foreground"}`}>
                        {s.disqualified ? "DQ" : fmtNum(s.score, 0)}
                      </span>
                    </div>
                    <div className="space-y-1">
                      {Object.entries(s.factors).map(([factor, pts]) => (
                        <div key={factor} className="flex items-center gap-2">
                          <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full transition-all duration-500"
                              style={{ width: `${Math.min(100, (pts / 25) * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground w-24 truncate">{factor}</span>
                          <span className="text-xs font-mono text-foreground/60 w-6 text-right">{pts}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </TabsContent>

        {/* Price chart */}
        <TabsContent value="chart" className="mt-4">
          <Card className="bg-card border-border">
            <CardHeader className="px-4 pt-4 pb-2">
              <CardTitle className="text-xs text-muted-foreground font-normal">Price — Last 12 Months</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {stock.price_history.length === 0 ? (
                <p className="text-muted-foreground text-sm">No price data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={stock.price_history}>
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                      tickFormatter={(d) => d.slice(5)}
                    />
                    <YAxis
                      tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                      width={60}
                      tickFormatter={(v) => v.toFixed(0)}
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
                    <Line type="monotone" dataKey="close" stroke="#9FE870" dot={false} strokeWidth={1.5} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* News */}
        <TabsContent value="news" className="mt-4">
          <div className="space-y-2">
            {stock.news.length === 0 ? (
              <p className="text-muted-foreground text-sm">No recent news.</p>
            ) : (
              stock.news.map((item) => (
                <div key={item.id} className="flex items-start gap-3 py-2.5 border-b border-border last:border-0 hover:bg-accent/30 transition-colors duration-150 rounded-sm">
                  <span className={`mt-0.5 text-xs font-medium shrink-0 ${sentimentColor(item.sentiment)}`}>
                    {item.sentiment === "positive" ? "+" : item.sentiment === "negative" ? "−" : "·"}
                  </span>
                  <div className="flex-1 min-w-0">
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-sm text-foreground hover:text-primary line-clamp-2 transition-colors cursor-pointer">
                        {item.headline}
                      </a>
                    ) : (
                      <p className="text-sm text-foreground line-clamp-2">{item.headline}</p>
                    )}
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {item.source} · {fmtDate(item.published_at)}
                      {item.category && (
                        <Badge variant="outline" className="ml-2 text-xs border-border text-muted-foreground px-1.5 py-0">
                          {item.category}
                        </Badge>
                      )}
                    </p>
                  </div>
                </div>
              ))
            )}
          </div>
        </TabsContent>

        {/* Events */}
        <TabsContent value="events" className="mt-4">
          <div className="space-y-2">
            {stock.events.length === 0 ? (
              <p className="text-muted-foreground text-sm">No upcoming events.</p>
            ) : (
              stock.events.map((ev, i) => (
                <div key={i} className="flex items-center gap-4 py-2 border-b border-border last:border-0 hover:bg-accent/30 transition-colors duration-150">
                  <span className="text-xs font-mono text-foreground/80 w-28 shrink-0">{fmtDate(ev.event_date)}</span>
                  <Badge variant="outline" className="text-xs border-border text-muted-foreground">
                    {ev.event_type}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{ev.description ?? ""}</span>
                </div>
              ))
            )}
          </div>
        </TabsContent>

        {/* Holding */}
        <TabsContent value="holding" className="mt-4">
          {stock.holding ? (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                { label: "Quantity", value: String(stock.holding.qty) },
                { label: "Avg Buy Price", value: fmtNum(stock.holding.avg_price, 2) },
                { label: "Current Value", value: stock.holding.current_value != null ? fmtINR(stock.holding.current_value) : "—" },
                { label: "Unrealized P&L", value: stock.holding.unrealized_pnl != null ? fmtINR(stock.holding.unrealized_pnl) : "—" },
                { label: "P&L %", value: stock.holding.unrealized_pnl_pct != null ? fmtPct(stock.holding.unrealized_pnl_pct) : "—" },
                { label: "Days Held", value: String(stock.holding.days_held) },
                { label: "% of Portfolio", value: stock.holding.pct_of_portfolio != null ? `${fmtNum(stock.holding.pct_of_portfolio, 1)}%` : "—" },
                { label: "LTCG/STCG", value: stock.holding.ltcg_status ?? "—" },
              ].map(({ label, value }, i) => (
                <Card key={label} className="bg-card border-border card-hover animate-fade-in-up" style={{ animationDelay: `${i * 50}ms` }}>
                  <CardContent className="px-4 py-3">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="text-base font-mono text-foreground mt-0.5">{value}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">You don&apos;t hold this stock.</p>
          )}
        </TabsContent>

        {/* Sentiment */}
        <TabsContent value="sentiment" className="mt-4">
          {stock.sentiment ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Card className="bg-card border-border card-hover">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-muted-foreground">Positive</p>
                    <p className="text-xl font-mono text-positive">{stock.sentiment.positive}</p>
                  </CardContent>
                </Card>
                <Card className="bg-card border-border card-hover">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-muted-foreground">Neutral</p>
                    <p className="text-xl font-mono text-muted-foreground">{stock.sentiment.neutral}</p>
                  </CardContent>
                </Card>
                <Card className="bg-card border-border card-hover">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-muted-foreground">Negative</p>
                    <p className="text-xl font-mono text-negative">{stock.sentiment.negative}</p>
                  </CardContent>
                </Card>
              </div>
              {stock.sentiment.trend && (
                <p className="text-sm text-muted-foreground">{stock.sentiment.trend}</p>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No sentiment data.</p>
          )}
        </TabsContent>

        {/* Forecasts */}
        <TabsContent value="forecasts" className="mt-4">
          {stock.forecasts ? (
            <div className="space-y-4">
              {stock.forecasts.note && (
                <Card className="bg-warning/10 border-warning/30">
                  <CardContent className="px-4 py-3 text-sm text-warning">
                    {stock.forecasts.note}
                  </CardContent>
                </Card>
              )}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: "Analysts", value: stock.forecasts.analyst_count != null ? String(stock.forecasts.analyst_count) : "—" },
                  { label: "Buy", value: stock.forecasts.buy_count != null ? String(stock.forecasts.buy_count) : "—" },
                  { label: "Hold", value: stock.forecasts.hold_count != null ? String(stock.forecasts.hold_count) : "—" },
                  { label: "Sell", value: stock.forecasts.sell_count != null ? String(stock.forecasts.sell_count) : "—" },
                  { label: "Target High", value: stock.forecasts.target_high != null ? fmtNum(stock.forecasts.target_high, 2) : "—" },
                  { label: "Target Avg", value: stock.forecasts.target_avg != null ? fmtNum(stock.forecasts.target_avg, 2) : "—" },
                  { label: "Target Low", value: stock.forecasts.target_low != null ? fmtNum(stock.forecasts.target_low, 2) : "—" },
                  { label: "Current Price", value: stock.forecasts.current_price != null ? fmtNum(stock.forecasts.current_price, 2) : "—" },
                  { label: "Consensus", value: stock.forecasts.consensus_rating ?? "—" },
                  { label: "Source", value: stock.forecasts.availability ?? "—" },
                ].map(({ label, value }, i) => (
                  <Card key={label} className="bg-card border-border card-hover animate-fade-in-up" style={{ animationDelay: `${i * 40}ms` }}>
                    <CardContent className="px-4 py-3">
                      <p className="text-xs text-muted-foreground">{label}</p>
                      <p className="text-base font-mono text-foreground mt-0.5">{value}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <Card className="bg-card border-border">
                <CardHeader className="px-4 pt-4 pb-2">
                  <CardTitle className="text-xs text-muted-foreground font-normal">Next Quarterly EPS Estimates</CardTitle>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  {stock.forecasts.quarterly_estimates.length === 0 ? (
                    <p className="text-muted-foreground text-sm">No forward EPS estimates were returned.</p>
                  ) : (
                    <div className="space-y-2">
                      {stock.forecasts.quarterly_estimates.map((estimate) => (
                        <div
                          key={`${estimate.period}-${estimate.fiscal_date ?? "na"}`}
                          className="grid grid-cols-2 md:grid-cols-5 gap-2 py-2 border-b border-border last:border-0 hover:bg-accent/30 transition-colors duration-150"
                        >
                          <span className="text-xs text-foreground/70">{estimate.period}</span>
                          <span className="text-xs text-muted-foreground">{estimate.fiscal_date ? fmtDate(estimate.fiscal_date) : "—"}</span>
                          <span className="text-xs font-mono text-foreground/80">
                            EPS {estimate.eps_estimate != null ? fmtNum(estimate.eps_estimate, 2) : "—"}
                          </span>
                          <span className="text-xs font-mono text-foreground/80">
                            Rev {estimate.revenue_estimate != null ? fmtNum(estimate.revenue_estimate, 0) : "—"}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {estimate.analyst_count != null ? `${estimate.analyst_count} analysts` : "—"}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No analyst forecast data stored for this stock yet.</p>
          )}
        </TabsContent>

        {/* Peers */}
        <TabsContent value="peers" className="mt-4">
          {stock.peers.length === 0 ? (
            <p className="text-muted-foreground text-sm">No peer comparison available yet.</p>
          ) : (
            <div className="space-y-4">
              {stock.peers_note && (
                <Card className="bg-muted/30 border-border">
                  <CardContent className="px-4 py-3 text-sm text-muted-foreground">
                    {stock.peers_note}
                  </CardContent>
                </Card>
              )}
              <Card className="bg-card border-border overflow-hidden">
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-border text-muted-foreground">
                          <th className="text-left px-4 py-2.5 font-normal">Ticker</th>
                          <th className="text-right px-4 py-2.5 font-normal">P/E</th>
                          <th className="text-right px-4 py-2.5 font-normal">ROE</th>
                          <th className="text-right px-4 py-2.5 font-normal">Growth</th>
                          <th className="text-right px-4 py-2.5 font-normal">Market Cap</th>
                          <th className="text-left px-4 py-2.5 font-normal">Buckets</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stock.peers.map((peer) => (
                          <tr key={peer.ticker} className="border-b border-border/40 last:border-0 hover:bg-accent/50 transition-colors duration-150">
                            <td className="px-4 py-2.5">
                              <a href={`/stocks/${peer.ticker}`} className="text-primary hover:text-primary/80 font-mono font-medium transition-colors cursor-pointer">
                                {peer.ticker}
                              </a>
                              {peer.company_name && (
                                <span className="ml-2 text-muted-foreground">{peer.company_name}</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                              {peer.pe_ratio != null ? fmtNum(peer.pe_ratio, 1) : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                              {peer.roe != null ? `${fmtNum(peer.roe, 1)}%` : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                              {peer.growth_rate != null ? `${fmtNum(peer.growth_rate, 1)}%` : "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                              {peer.market_cap != null
                                ? stock.country === "IN"
                                  ? fmtINR(peer.market_cap)
                                  : `$${(peer.market_cap / 1e9).toFixed(1)}B`
                                : "—"}
                            </td>
                            <td className="px-4 py-2.5">
                              <div className="flex items-center gap-1 flex-wrap">
                                {peer.bucket_membership.length > 0 ? (
                                  peer.bucket_membership.map((bucket) => (
                                    <Badge
                                      key={`${peer.ticker}-${bucket}`}
                                      variant="outline"
                                      className="border-border text-muted-foreground text-[10px]"
                                    >
                                      {bucketLabel(bucket)}
                                    </Badge>
                                  ))
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

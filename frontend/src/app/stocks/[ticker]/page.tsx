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

  if (loading) return <p className="text-slate-500 text-sm">Loading {ticker}…</p>;
  if (!stock) return <p className="text-slate-500 text-sm">Stock not found.</p>;

  const fund = stock.fundamentals;

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 font-mono flex items-center gap-2">
            {stock.ticker}
            <span className="text-base text-slate-400 font-normal">{countryFlag(stock.country)}</span>
          </h1>
          <p className="text-slate-400 text-sm">{stock.name}</p>
          {stock.sector && (
            <p className="text-slate-600 text-xs mt-0.5">{stock.sector}</p>
          )}
        </div>
        <div className="text-right">
          <p className="text-2xl font-mono font-semibold text-slate-100">
            {stock.current_price != null ? fmtNum(stock.current_price, 2) : "—"}
          </p>
          <p className="text-xs text-slate-500 mt-0.5">
            52w: {fmtNum(stock.week_52_low, 1)} – {fmtNum(stock.week_52_high, 1)}
          </p>
        </div>
      </div>

      {/* Bucket badges */}
      {stock.scores.filter((s) => !s.disqualified && s.score > 0).length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
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
        <Card className="bg-indigo-950/40 border-indigo-900/50">
          <CardContent className="px-4 py-3 text-sm text-indigo-200">
            {stock.plain_english}
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="bg-slate-900 border-b border-slate-800 rounded-none h-auto p-0 w-full justify-start gap-0">
          {["overview", "score", "chart", "news", "events", "holding", "sentiment", "forecasts", "peers"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:bg-transparent data-[state=active]:text-indigo-300 text-slate-500 text-xs px-4 py-2.5 capitalize"
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
            ].map(({ label, value }) => (
              <Card key={label} className="bg-slate-900 border-slate-800">
                <CardContent className="px-4 py-3">
                  <p className="text-xs text-slate-500">{label}</p>
                  <p className="text-lg font-mono text-slate-100 mt-0.5">{value}</p>
                </CardContent>
              </Card>
            ))}
          </div>
          {stock.description && (
            <p className="text-sm text-slate-400 mt-4 leading-relaxed">{stock.description}</p>
          )}
        </TabsContent>

        {/* Score breakdown */}
        <TabsContent value="score" className="mt-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Radar */}
            <Card className="bg-slate-900 border-slate-800">
              <CardHeader className="px-4 pt-4 pb-2">
                <CardTitle className="text-xs text-slate-500 font-normal">Score Radar</CardTitle>
              </CardHeader>
              <CardContent className="px-4 pb-4">
                <ResponsiveContainer width="100%" height={220}>
                  <RadarChart data={stock.scores.map((s) => ({ name: bucketLabel(s.bucket).split(" ")[0], score: s.score }))}>
                    <PolarGrid stroke="#334155" />
                    <PolarAngleAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 11 }} />
                    <Radar dataKey="score" stroke="#6366f1" fill="#6366f1" fillOpacity={0.25} />
                  </RadarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Factor breakdown per bucket */}
            <div className="space-y-3">
              {stock.scores.map((s) => (
                <Card key={s.bucket} className="bg-slate-900 border-slate-800">
                  <CardContent className="px-4 py-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-slate-300">{bucketLabel(s.bucket)}</span>
                      <span className={`text-xs font-mono ${s.disqualified ? "text-red-400" : "text-slate-100"}`}>
                        {s.disqualified ? "DQ" : fmtNum(s.score, 0)}
                      </span>
                    </div>
                    <div className="space-y-1">
                      {Object.entries(s.factors).map(([factor, pts]) => (
                        <div key={factor} className="flex items-center gap-2">
                          <div className="flex-1 h-1 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-indigo-500 rounded-full"
                              style={{ width: `${Math.min(100, (pts / 25) * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500 w-24 truncate">{factor}</span>
                          <span className="text-xs font-mono text-slate-400 w-6 text-right">{pts}</span>
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
          <Card className="bg-slate-900 border-slate-800">
            <CardHeader className="px-4 pt-4 pb-2">
              <CardTitle className="text-xs text-slate-500 font-normal">Price — Last 12 Months</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              {stock.price_history.length === 0 ? (
                <p className="text-slate-600 text-sm">No price data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={stock.price_history}>
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#64748b", fontSize: 10 }}
                      tickFormatter={(d) => d.slice(5)}
                    />
                    <YAxis
                      tick={{ fill: "#64748b", fontSize: 10 }}
                      width={60}
                      tickFormatter={(v) => v.toFixed(0)}
                    />
                    <Tooltip
                      contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
                      labelStyle={{ color: "#94a3b8", fontSize: 11 }}
                      itemStyle={{ color: "#e2e8f0", fontSize: 11 }}
                    />
                    <Line type="monotone" dataKey="close" stroke="#6366f1" dot={false} strokeWidth={1.5} />
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
              <p className="text-slate-600 text-sm">No recent news.</p>
            ) : (
              stock.news.map((item) => (
                <div key={item.id} className="flex items-start gap-3 py-2.5 border-b border-slate-800 last:border-0">
                  <span className={`mt-0.5 text-xs font-medium shrink-0 ${sentimentColor(item.sentiment)}`}>
                    {item.sentiment === "positive" ? "+" : item.sentiment === "negative" ? "−" : "·"}
                  </span>
                  <div className="flex-1 min-w-0">
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-sm text-slate-200 hover:text-indigo-300 line-clamp-2">
                        {item.headline}
                      </a>
                    ) : (
                      <p className="text-sm text-slate-200 line-clamp-2">{item.headline}</p>
                    )}
                    <p className="text-xs text-slate-600 mt-0.5">
                      {item.source} · {fmtDate(item.published_at)}
                      {item.category && (
                        <Badge variant="outline" className="ml-2 text-xs border-slate-700 text-slate-500 px-1.5 py-0">
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
              <p className="text-slate-600 text-sm">No upcoming events.</p>
            ) : (
              stock.events.map((ev, i) => (
                <div key={i} className="flex items-center gap-4 py-2 border-b border-slate-800 last:border-0">
                  <span className="text-xs font-mono text-slate-300 w-28 shrink-0">{fmtDate(ev.event_date)}</span>
                  <Badge variant="outline" className="text-xs border-slate-700 text-slate-400">
                    {ev.event_type}
                  </Badge>
                  <span className="text-xs text-slate-500">{ev.description ?? ""}</span>
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
              ].map(({ label, value }) => (
                <Card key={label} className="bg-slate-900 border-slate-800">
                  <CardContent className="px-4 py-3">
                    <p className="text-xs text-slate-500">{label}</p>
                    <p className="text-base font-mono text-slate-100 mt-0.5">{value}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">You don&apos;t hold this stock.</p>
          )}
        </TabsContent>

        {/* Sentiment */}
        <TabsContent value="sentiment" className="mt-4">
          {stock.sentiment ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Card className="bg-slate-900 border-slate-800">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-slate-500">Positive</p>
                    <p className="text-xl font-mono text-green-400">{stock.sentiment.positive}</p>
                  </CardContent>
                </Card>
                <Card className="bg-slate-900 border-slate-800">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-slate-500">Neutral</p>
                    <p className="text-xl font-mono text-slate-400">{stock.sentiment.neutral}</p>
                  </CardContent>
                </Card>
                <Card className="bg-slate-900 border-slate-800">
                  <CardContent className="px-4 py-3 text-center">
                    <p className="text-xs text-slate-500">Negative</p>
                    <p className="text-xl font-mono text-red-400">{stock.sentiment.negative}</p>
                  </CardContent>
                </Card>
              </div>
              {stock.sentiment.trend && (
                <p className="text-sm text-slate-400">{stock.sentiment.trend}</p>
              )}
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No sentiment data.</p>
          )}
        </TabsContent>

        {/* Forecasts */}
        <TabsContent value="forecasts" className="mt-4">
          {stock.forecasts ? (
            <div className="space-y-4">
              {stock.forecasts.note && (
                <Card className="bg-amber-950/30 border-amber-900/40">
                  <CardContent className="px-4 py-3 text-sm text-amber-200">
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
                ].map(({ label, value }) => (
                  <Card key={label} className="bg-slate-900 border-slate-800">
                    <CardContent className="px-4 py-3">
                      <p className="text-xs text-slate-500">{label}</p>
                      <p className="text-base font-mono text-slate-100 mt-0.5">{value}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
              <Card className="bg-slate-900 border-slate-800">
                <CardHeader className="px-4 pt-4 pb-2">
                  <CardTitle className="text-xs text-slate-500 font-normal">Next Quarterly EPS Estimates</CardTitle>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  {stock.forecasts.quarterly_estimates.length === 0 ? (
                    <p className="text-slate-500 text-sm">No forward EPS estimates were returned.</p>
                  ) : (
                    <div className="space-y-2">
                      {stock.forecasts.quarterly_estimates.map((estimate) => (
                        <div
                          key={`${estimate.period}-${estimate.fiscal_date ?? "na"}`}
                          className="grid grid-cols-2 md:grid-cols-5 gap-2 py-2 border-b border-slate-800 last:border-0"
                        >
                          <span className="text-xs text-slate-400">{estimate.period}</span>
                          <span className="text-xs text-slate-500">{estimate.fiscal_date ? fmtDate(estimate.fiscal_date) : "—"}</span>
                          <span className="text-xs font-mono text-slate-300">
                            EPS {estimate.eps_estimate != null ? fmtNum(estimate.eps_estimate, 2) : "—"}
                          </span>
                          <span className="text-xs font-mono text-slate-300">
                            Rev {estimate.revenue_estimate != null ? fmtNum(estimate.revenue_estimate, 0) : "—"}
                          </span>
                          <span className="text-xs text-slate-500">
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
            <p className="text-slate-500 text-sm">No analyst forecast data stored for this stock yet.</p>
          )}
        </TabsContent>

        {/* Peers */}
        <TabsContent value="peers" className="mt-4">
          {stock.peers.length === 0 ? (
            <p className="text-slate-500 text-sm">No peer comparison available yet.</p>
          ) : (
            <div className="space-y-4">
              {stock.peers_note && (
                <Card className="bg-slate-950 border-slate-800">
                  <CardContent className="px-4 py-3 text-sm text-slate-400">
                    {stock.peers_note}
                  </CardContent>
                </Card>
              )}
              <Card className="bg-slate-900 border-slate-800">
                <CardContent className="p-0">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-slate-800 text-slate-600">
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
                        <tr key={peer.ticker} className="border-b border-slate-800/40 last:border-0">
                          <td className="px-4 py-2.5">
                            <a href={`/stocks/${peer.ticker}`} className="text-indigo-400 hover:text-indigo-300 font-mono font-medium">
                              {peer.ticker}
                            </a>
                            {peer.company_name && (
                              <span className="ml-2 text-slate-600">{peer.company_name}</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                            {peer.pe_ratio != null ? fmtNum(peer.pe_ratio, 1) : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                            {peer.roe != null ? `${fmtNum(peer.roe, 1)}%` : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                            {peer.growth_rate != null ? `${fmtNum(peer.growth_rate, 1)}%` : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-slate-300">
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
                                    className="border-slate-700 text-slate-400 text-[10px]"
                                  >
                                    {bucketLabel(bucket)}
                                  </Badge>
                                ))
                              ) : (
                                <span className="text-slate-600">—</span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

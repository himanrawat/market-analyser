"use client";

import { useEffect, useState } from "react";
import { api, DashboardResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  fmtNum,
  fmtPct,
  fmtDate,
  regimeLabel,
  regimeBadgeClass,
} from "@/lib/format";
import { Activity, Calendar, TrendingUp, DollarSign } from "lucide-react";

function SkeletonCard() {
  return (
    <Card className="bg-card border-border">
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="h-3 w-20 skeleton-shimmer rounded" />
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <div className="h-7 w-24 skeleton-shimmer rounded mt-1" />
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.dashboard()
      .then((d) => {
        console.log("[Dashboard] data received:", d);
        console.log("[Dashboard] indices:", d.indices);
        console.log("[Dashboard] macro:", d.macro);
        console.log("[Dashboard] vix:", d.vix);
        setData(d);
      })
      .catch((err) => console.error("[Dashboard] fetch error:", err))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6 max-w-5xl">
        <div>
          <div className="h-6 w-32 skeleton-shimmer rounded" />
          <div className="h-4 w-48 skeleton-shimmer rounded mt-2" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-muted-foreground text-sm">
        Could not load dashboard. Is the API running on{" "}
        <code className="text-foreground/60 bg-muted px-1.5 py-0.5 rounded text-xs">localhost:8000</code>?
      </div>
    );
  }

  const { macro, vix, indices, upcoming_events } = data;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="animate-fade-in-up">
        <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-0.5">
          Market overview as of {fmtDate(data.as_of)}
        </p>
      </div>

      {/* Regime + VIX row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-card border-border card-hover animate-fade-in-up stagger-1">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-muted-foreground font-normal flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" /> Market Regime
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div
              className={`inline-flex items-center px-2.5 py-1 rounded-full border text-sm font-semibold ${regimeBadgeClass(macro.regime)}`}
            >
              {regimeLabel(macro.regime)}
            </div>
            {macro.shock_regime && (
              <p className="text-xs text-negative mt-1.5">Shock regime active</p>
            )}
          </CardContent>
        </Card>

        <Card className="bg-card border-border card-hover animate-fade-in-up stagger-2">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-muted-foreground font-normal">India VIX</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-foreground">
              {fmtNum(vix.india_vix, 1)}
            </p>
          </CardContent>
        </Card>

        {/* US VIX — Phase 2 (US market) */}
        {/* <Card className="bg-card border-border card-hover animate-fade-in-up stagger-3">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-muted-foreground font-normal">US VIX</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-foreground">
              {fmtNum(vix.us_vix, 1)}
            </p>
          </CardContent>
        </Card> */}

        <Card className="bg-card border-border card-hover animate-fade-in-up stagger-3">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-muted-foreground font-normal flex items-center gap-1.5">
              <DollarSign className="h-3.5 w-3.5" /> USD / INR
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-foreground">
              {fmtNum(macro.usd_inr, 2)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Macro rates — Phase 1: India indicators only.
          Fed Funds Rate and US CPI YoY are commented out until Phase 2 (US market). */}
      <div className="grid grid-cols-2 md:grid-cols-2 gap-4">
        {[
          // { label: "Fed Funds Rate", value: macro.fed_funds_rate }, // Phase 2 (US market)
          { label: "RBI Repo Rate", value: macro.rbi_repo_rate },
          // { label: "US CPI YoY", value: macro.us_cpi_yoy }, // Phase 2 (US market)
          { label: "India CPI YoY", value: macro.india_cpi_yoy },
        ].map(({ label, value }, i) => (
          <Card key={label} className="bg-card border-border card-hover animate-fade-in-up" style={{ animationDelay: `${(i + 4) * 50}ms` }}>
            <CardHeader className="pb-2 pt-4 px-4">
              <CardTitle className="text-xs text-muted-foreground font-normal">{label}</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <p className="text-xl font-mono text-foreground">
                {value === null || value === undefined ? "—" : `${value.toFixed(2)}%`}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Indices */}
      {indices.length > 0 && (
        <div className="animate-fade-in-up" style={{ animationDelay: "300ms" }}>
          <h2 className="text-sm font-semibold text-muted-foreground mb-3 flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4" /> Indices
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {indices.map((idx, i) => (
              <Card key={idx.name} className="bg-card border-border card-hover animate-fade-in-up" style={{ animationDelay: `${(i + 6) * 50}ms` }}>
                <CardContent className="px-4 py-4">
                  <p className="text-xs text-muted-foreground mb-1">{idx.name}</p>
                  <p className="text-lg font-mono text-foreground">
                    {idx.value === null || idx.value === undefined
                      ? "—"
                      : idx.value.toLocaleString("en-IN")}
                  </p>
                  {idx.change_1d_pct !== null && idx.change_1d_pct !== undefined && (
                    <p
                      className={`text-xs font-medium mt-0.5 ${
                        idx.change_1d_pct >= 0 ? "text-positive" : "text-negative"
                      }`}
                    >
                      {fmtPct(idx.change_1d_pct)} today
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Upcoming events */}
      <div className="animate-fade-in-up" style={{ animationDelay: "400ms" }}>
        <h2 className="text-sm font-semibold text-muted-foreground mb-3 flex items-center gap-1.5">
          <Calendar className="h-4 w-4" /> Upcoming Events · Next 14 Days
        </h2>
        {upcoming_events.length > 0 ? (
          <Card className="bg-card border-border overflow-hidden">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-muted-foreground text-xs">
                      <th className="text-left px-4 py-2.5 font-normal">Date</th>
                      <th className="text-left px-4 py-2.5 font-normal">Ticker</th>
                      <th className="text-left px-4 py-2.5 font-normal">Type</th>
                      <th className="text-left px-4 py-2.5 font-normal">Description</th>
                    </tr>
                  </thead>
                  <tbody>
                    {upcoming_events.map((ev, i) => (
                      <tr
                        key={`${ev.event_date}-${ev.ticker ?? "market"}-${ev.event_type}-${i}`}
                        className="border-b border-border/50 last:border-0 hover:bg-accent/50 transition-colors duration-150"
                      >
                        <td className="px-4 py-2.5 font-mono text-muted-foreground text-xs">
                          {fmtDate(ev.event_date)}
                        </td>
                        <td className="px-4 py-2.5">
                          {ev.ticker ? (
                            <a
                              href={`/stocks/${ev.ticker}`}
                              className="text-primary hover:text-primary/80 font-mono text-xs transition-colors cursor-pointer"
                            >
                              {ev.ticker}
                            </a>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          <Badge
                            variant="outline"
                            className="text-xs border-border text-muted-foreground"
                          >
                            {ev.event_type}
                          </Badge>
                        </td>
                        <td className="px-4 py-2.5 text-muted-foreground text-xs">
                          {ev.description ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        ) : (
          <p className="text-muted-foreground text-sm">No upcoming events in the next 14 days.</p>
        )}
      </div>
    </div>
  );
}

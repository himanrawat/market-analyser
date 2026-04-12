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
    return <div className="text-slate-500 text-sm">Loading dashboard…</div>;
  }

  if (!data) {
    return (
      <div className="text-slate-500 text-sm">
        Could not load dashboard. Is the API running on{" "}
        <code className="text-slate-400">localhost:8000</code>?
      </div>
    );
  }

  const { macro, vix, indices, upcoming_events } = data;

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Dashboard</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Market overview as of {fmtDate(data.as_of)}
        </p>
      </div>

      {/* Regime + VIX row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-500 font-normal flex items-center gap-1.5">
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
              <p className="text-xs text-red-400 mt-1.5">Shock regime active</p>
            )}
          </CardContent>
        </Card>

        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-500 font-normal">India VIX</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-slate-100">
              {fmtNum(vix.india_vix, 1)}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-500 font-normal">US VIX</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-slate-100">
              {fmtNum(vix.us_vix, 1)}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-500 font-normal flex items-center gap-1.5">
              <DollarSign className="h-3.5 w-3.5" /> USD / INR
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <p className="text-2xl font-mono font-semibold text-slate-100">
              {fmtNum(macro.usd_inr, 2)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Macro rates */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Fed Funds Rate", value: macro.fed_funds_rate },
          { label: "RBI Repo Rate", value: macro.rbi_repo_rate },
          { label: "US CPI YoY", value: macro.us_cpi_yoy },
          { label: "India CPI YoY", value: macro.india_cpi_yoy },
        ].map(({ label, value }) => (
          <Card key={label} className="bg-slate-900 border-slate-800">
            <CardHeader className="pb-2 pt-4 px-4">
              <CardTitle className="text-xs text-slate-500 font-normal">{label}</CardTitle>
            </CardHeader>
            <CardContent className="px-4 pb-4">
              <p className="text-xl font-mono text-slate-100">
                {value === null || value === undefined ? "—" : `${value.toFixed(2)}%`}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Indices */}
      {indices.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
            <TrendingUp className="h-4 w-4" /> Indices
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {indices.map((idx) => (
              <Card key={idx.name} className="bg-slate-900 border-slate-800">
                <CardContent className="px-4 py-4">
                  <p className="text-xs text-slate-500 mb-1">{idx.name}</p>
                  <p className="text-lg font-mono text-slate-100">
                    {idx.value === null || idx.value === undefined
                      ? "—"
                      : idx.value.toLocaleString("en-IN")}
                  </p>
                  {idx.change_1d_pct !== null && idx.change_1d_pct !== undefined && (
                    <p
                      className={`text-xs font-medium mt-0.5 ${
                        idx.change_1d_pct >= 0 ? "text-green-400" : "text-red-400"
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
      <div>
        <h2 className="text-sm font-semibold text-slate-400 mb-3 flex items-center gap-1.5">
          <Calendar className="h-4 w-4" /> Upcoming Events · Next 14 Days
        </h2>
        {upcoming_events.length > 0 ? (
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs">
                    <th className="text-left px-4 py-2.5 font-normal">Date</th>
                    <th className="text-left px-4 py-2.5 font-normal">Ticker</th>
                    <th className="text-left px-4 py-2.5 font-normal">Type</th>
                    <th className="text-left px-4 py-2.5 font-normal">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {upcoming_events.map((ev) => (
                    <tr
                      key={`${ev.event_date}-${ev.ticker ?? "market"}-${ev.event_type}`}
                      className="border-b border-slate-800/50 last:border-0"
                    >
                      <td className="px-4 py-2.5 font-mono text-slate-300 text-xs">
                        {fmtDate(ev.event_date)}
                      </td>
                      <td className="px-4 py-2.5">
                        {ev.ticker ? (
                          <a
                            href={`/stocks/${ev.ticker}`}
                            className="text-indigo-400 hover:text-indigo-300 font-mono text-xs"
                          >
                            {ev.ticker}
                          </a>
                        ) : (
                          <span className="text-slate-500 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge
                          variant="outline"
                          className="text-xs border-slate-700 text-slate-400"
                        >
                          {ev.event_type}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-slate-400 text-xs">
                        {ev.description ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        ) : (
          <p className="text-slate-600 text-sm">No upcoming events in the next 14 days.</p>
        )}
      </div>
    </div>
  );
}

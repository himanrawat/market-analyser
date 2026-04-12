"use client";

import { DashboardResponse } from "@/lib/api";
import { fmtNum, fmtPct, regimeLabel, regimeBadgeClass } from "@/lib/format";

interface Props {
  data: DashboardResponse | null;
}

export function MacroHeader({ data }: Props) {
  if (!data) {
    return (
      <div className="h-10 bg-slate-900 border-b border-slate-800 flex items-center px-4 text-slate-500 text-xs">
        Loading macro data…
      </div>
    );
  }

  const { macro, vix, indices } = data;

  return (
    <div className="bg-slate-900 border-b border-slate-800 flex items-center gap-6 px-4 py-2 text-xs overflow-x-auto whitespace-nowrap">
      {/* Index strip */}
      {indices.map((idx) => (
        <div key={idx.name} className="flex items-center gap-1.5">
          <span className="text-slate-400">{idx.name}</span>
          <span className="text-slate-100 font-mono">
            {idx.value != null ? idx.value.toLocaleString("en-IN") : "—"}
          </span>
          {idx.change_1d_pct != null && (
            <span className={idx.change_1d_pct >= 0 ? "text-green-400" : "text-red-400"}>
              {fmtPct(idx.change_1d_pct, 2)}
            </span>
          )}
        </div>
      ))}

      <div className="w-px h-4 bg-slate-700 shrink-0" />

      {/* VIX */}
      <div className="flex items-center gap-1.5">
        <span className="text-slate-400">India VIX</span>
        <span className="text-slate-100 font-mono">{fmtNum(vix.india_vix, 1)}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="text-slate-400">US VIX</span>
        <span className="text-slate-100 font-mono">{fmtNum(vix.us_vix, 1)}</span>
      </div>

      <div className="w-px h-4 bg-slate-700 shrink-0" />

      {/* USD/INR */}
      <div className="flex items-center gap-1.5">
        <span className="text-slate-400">USD/INR</span>
        <span className="text-slate-100 font-mono">{fmtNum(macro.usd_inr, 2)}</span>
      </div>

      <div className="w-px h-4 bg-slate-700 shrink-0" />

      {/* Regime */}
      <div
        className={`px-2 py-0.5 rounded-full border text-xs font-semibold ${regimeBadgeClass(macro.regime)}`}
      >
        {regimeLabel(macro.regime)}
      </div>
    </div>
  );
}

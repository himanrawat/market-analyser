"use client";

import { DashboardResponse } from "@/lib/api";
import { fmtNum, fmtPct, regimeLabel, regimeBadgeClass } from "@/lib/format";

interface Props {
  data: DashboardResponse | null;
}

export function MacroHeader({ data }: Props) {
  if (!data) {
    return (
      <div className="h-10 bg-card border-b border-border flex items-center px-4 text-muted-foreground text-xs">
        <div className="flex items-center gap-3">
          <div className="h-3 w-16 skeleton-shimmer rounded" />
          <div className="h-3 w-20 skeleton-shimmer rounded" />
          <div className="h-3 w-14 skeleton-shimmer rounded" />
        </div>
      </div>
    );
  }

  const { macro, vix, indices } = data;

  return (
    <div className="bg-card border-b border-border flex items-center gap-4 md:gap-6 px-4 py-2 text-xs overflow-x-auto whitespace-nowrap scrollbar-thin">
      {/* Index strip */}
      {indices.map((idx, i) => (
        <div
          key={idx.name}
          className="flex items-center gap-1.5 animate-fade-in-up"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          <span className="text-muted-foreground">{idx.name}</span>
          <span className="text-foreground font-mono font-medium">
            {idx.value != null ? idx.value.toLocaleString("en-IN") : "—"}
          </span>
          {idx.change_1d_pct != null && (
            <span className={idx.change_1d_pct >= 0 ? "text-positive" : "text-negative"}>
              {fmtPct(idx.change_1d_pct, 2)}
            </span>
          )}
        </div>
      ))}

      <div className="w-px h-4 bg-border shrink-0" />

      {/* VIX */}
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">India VIX</span>
        <span className="text-foreground font-mono font-medium">{fmtNum(vix.india_vix, 1)}</span>
      </div>

      <div className="w-px h-4 bg-border shrink-0" />

      {/* USD/INR */}
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">USD/INR</span>
        <span className="text-foreground font-mono font-medium">{fmtNum(macro.usd_inr, 2)}</span>
      </div>

      <div className="w-px h-4 bg-border shrink-0" />

      {/* Regime */}
      <div
        className={`px-2.5 py-0.5 rounded-full border text-xs font-semibold ${regimeBadgeClass(macro.regime)}`}
      >
        {regimeLabel(macro.regime)}
      </div>
    </div>
  );
}

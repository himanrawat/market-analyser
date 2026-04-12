/** Shared formatting helpers. */

export function fmtINR(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e7) return `₹${(value / 1e7).toFixed(1)}Cr`;
  if (value >= 1e5) return `₹${(value / 1e5).toFixed(1)}L`;
  return `₹${value.toFixed(0)}`;
}

export function fmtUSD(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return `$${value.toFixed(0)}`;
}

export function fmtPct(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

export function fmtNum(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "—";
  return value.toFixed(decimals);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function bucketLabel(bucket: string): string {
  const map: Record<string, string> = {
    quality_value: "Quality + Value",
    momentum: "Momentum",
    quality_momentum: "Quality + Momentum",
    dividend_growth: "Dividend Growth",
  };
  return map[bucket] ?? bucket;
}

export function bucketColor(bucket: string): string {
  const map: Record<string, string> = {
    quality_value: "bg-blue-500",
    momentum: "bg-orange-500",
    quality_momentum: "bg-purple-500",
    dividend_growth: "bg-green-500",
  };
  return map[bucket] ?? "bg-slate-500";
}

export function bucketBorderColor(bucket: string): string {
  const map: Record<string, string> = {
    quality_value: "border-blue-500",
    momentum: "border-orange-500",
    quality_momentum: "border-purple-500",
    dividend_growth: "border-green-500",
  };
  return map[bucket] ?? "border-slate-500";
}

export function actionColor(action: string): string {
  const normalized = action.toLowerCase();
  const map: Record<string, string> = {
    buy: "text-green-400 font-bold",
    add: "text-emerald-400 font-semibold",
    hold: "text-slate-400",
    trim: "text-yellow-400 font-semibold",
    sell: "text-red-400 font-bold",
    skip_month: "text-yellow-400 font-semibold",
  };
  return map[normalized] ?? "text-slate-400";
}

export function sentimentColor(s: string): string {
  if (s === "positive") return "text-green-400";
  if (s === "negative") return "text-red-400";
  return "text-slate-400";
}

export function regimeLabel(regime: string): string {
  const normalized = regime.toLowerCase();
  const map: Record<string, string> = {
    risk_on: "Risk-On",
    caution: "Caution",
    risk_off: "Risk-Off",
  };
  return map[normalized] ?? regime;
}

export function regimeBadgeClass(regime: string): string {
  const normalized = regime.toLowerCase();
  if (normalized === "risk_on") return "bg-green-500/20 text-green-400 border-green-500/30";
  if (normalized === "caution") return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/20 text-red-400 border-red-500/30";
}

export function countryFlag(country: string): string {
  return country === "IN" ? "🇮🇳" : "🇺🇸";
}

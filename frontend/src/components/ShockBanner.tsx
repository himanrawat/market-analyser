"use client";

import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import type { ShockBannerStatus } from "@/lib/api";
import { fmtDate } from "@/lib/format";

interface Props {
  shock: ShockBannerStatus;
}

export function ShockBanner({ shock }: Props) {
  const [dismissed, setDismissed] = useState(false);

  if (!shock.active || dismissed) return null;

  const isRed = shock.banner?.toLowerCase() === "red";

  return (
    <div
      className={`relative w-full px-4 py-3 flex items-start gap-3 text-sm animate-slide-down ${
        isRed
          ? "bg-red-600 text-white"
          : "bg-amber-500 text-amber-950"
      }`}
    >
      <AlertTriangle className="mt-0.5 shrink-0 h-4 w-4 animate-pulse" />
      <div className="flex-1 min-w-0">
        <span className="font-semibold">
          {isRed ? "MARKET SHOCK DETECTED" : "MARKET CAUTION"}
          {shock.triggered_at ? ` · ${fmtDate(shock.triggered_at)}` : ""}
        </span>
        {shock.headline && (
          <span className="ml-2 opacity-90 truncate">{shock.headline}</span>
        )}
        {isRed && (
          <span className="ml-2 opacity-80 text-xs">
            — Pause new buys for the rest of the month. Do NOT sell existing holdings.
          </span>
        )}
      </div>
      <button
        onClick={() => setDismissed(true)}
        className="shrink-0 opacity-70 hover:opacity-100 transition-opacity cursor-pointer"
        title="Dismiss for this session"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

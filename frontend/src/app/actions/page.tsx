"use client";

import { useCallback, useDeferredValue, useEffect, useState } from "react";
import { api, ActionsResponse, ActionRow, ApiError, Bucket } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import {
  fmtDate,
  fmtINR,
  fmtNum,
  bucketLabel,
  actionColor,
  countryFlag,
  regimeBadgeClass,
  regimeLabel,
} from "@/lib/format";
import { CheckSquare, RefreshCw, SkipForward, Zap } from "lucide-react";

const BUCKET_ORDER: Bucket[] = [
  "quality_value",
  "momentum",
  "quality_momentum",
  "dividend_growth",
];

const DEFAULT_ALLOC: Record<Bucket, number> = {
  quality_value: 60,
  momentum: 0,
  quality_momentum: 40,
  dividend_growth: 0,
};

function normalizeAction(action: string) {
  return action.toLowerCase();
}

function actionLabel(action: string) {
  return normalizeAction(action).replace("_", " ").toUpperCase();
}

function defaultQty(row: ActionRow, price?: number) {
  const normalized = normalizeAction(row.action);
  if (normalized === "sell" || normalized === "trim") {
    return row.current_qty ? String(row.current_qty) : "";
  }
  if (row.suggested_qty != null) return row.suggested_qty.toFixed(2);
  if (row.suggested_amount != null && price && price > 0) {
    return (row.suggested_amount / price).toFixed(2);
  }
  return "";
}

export default function ActionsPage() {
  const [data, setData] = useState<ActionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [freshCapital, setFreshCapital] = useState(15000);
  const [sellProceeds, setSellProceeds] = useState(0);
  const [alloc, setAlloc] = useState<Record<Bucket, number>>({ ...DEFAULT_ALLOC });
  const [refreshing, setRefreshing] = useState(false);
  const [livePrices, setLivePrices] = useState<Record<string, number>>({});
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [executeRow, setExecuteRow] = useState<ActionRow | null>(null);
  const [fillPrice, setFillPrice] = useState("");
  const [qty, setQty] = useState("");
  const [notes, setNotes] = useState("");
  const [lesson, setLesson] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [emptyStateMessage, setEmptyStateMessage] = useState<string | null>(null);

  const deferredFreshCapital = useDeferredValue(freshCapital);
  const deferredSellProceeds = useDeferredValue(sellProceeds);
  const deferredAlloc = useDeferredValue(alloc);

  const load = useCallback(() => {
    setLoading(true);
    setEmptyStateMessage(null);
    api
      .actions({
        fresh_capital: deferredFreshCapital,
        sell_proceeds: deferredSellProceeds,
        bucket_allocations: deferredAlloc,
      })
      .then((d) => {
        console.log(`[Actions] received run_date=${d.run_date} regime=${d.macro_regime} shock=${d.shock_regime} rows=${d.rows.length}`);
        d.rows.forEach((r) => console.log(`[Actions]   ${r.action} ${r.ticker} bucket=${r.bucket} score=${r.score} rank=${r.rank}`));
        setData(d);
      })
      .catch((err) => {
        if (
          err instanceof ApiError
          && err.status === 404
          && (err.detail ?? "").includes("No rebalance snapshot found")
        ) {
          setData(null);
          setEmptyStateMessage("No action data yet. Run the pipeline first to create the monthly rebalance snapshot.");
          return;
        }
        console.error("[Actions] fetch error:", err);
        setEmptyStateMessage("Could not load actions. Check that the API is running and try again.");
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [deferredAlloc, deferredFreshCapital, deferredSellProceeds]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRefreshPrices() {
    setRefreshing(true);
    try {
      const res = await api.refreshPrices();
      setLivePrices(res.prices ?? {});
    } finally {
      setRefreshing(false);
    }
  }

  async function handleSkip() {
    if (!skipReason.trim()) return;
    await api.skipMonth({ reason: skipReason.trim() });
    setSkipOpen(false);
    setSkipReason("");
    load();
  }

  function openExecuteDialog(row: ActionRow) {
    const price = livePrices[row.ticker] ?? row.current_price ?? undefined;
    setExecuteRow(row);
    setFillPrice(price != null ? String(price) : "");
    setQty(defaultQty(row, price));
    setNotes("");
    setLesson("");
    setActionError(null);
  }

  async function handleExecute() {
    if (!executeRow) return;
    const parsedQty = Number(qty);
    const parsedPrice = Number(fillPrice);

    if (!parsedQty || parsedQty <= 0 || !parsedPrice || parsedPrice <= 0) {
      setActionError("Fill price and quantity must both be greater than zero.");
      return;
    }
    if (["sell", "trim"].includes(normalizeAction(executeRow.action)) && !lesson.trim()) {
      setActionError("Exit actions require a one-line lesson.");
      return;
    }

    setSubmitting(true);
    setActionError(null);
    try {
      await api.executeAction(executeRow.ticker, {
        action: executeRow.action,
        bucket: executeRow.bucket,
        country: executeRow.country,
        qty: parsedQty,
        fill_price: parsedPrice,
        notes: notes.trim() || undefined,
        lesson: lesson.trim() || undefined,
      });
      setExecuteRow(null);
      setFillPrice("");
      setQty("");
      setNotes("");
      setLesson("");
      load();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not mark the action as executed.");
    } finally {
      setSubmitting(false);
    }
  }

  const totalAllocPct = Object.values(alloc).reduce((sum, value) => sum + value, 0);
  const actionableCount =
    data?.rows.filter((row) => normalizeAction(row.action) !== "hold").length ?? 0;
  const executedCount =
    data?.rows.filter((row) => normalizeAction(row.action) !== "hold" && row.executed).length ?? 0;

  if (loading) {
    return (
      <div className="space-y-6 max-w-6xl">
        <div className="h-6 w-40 skeleton-shimmer rounded" />
        <Card className="bg-card border-border">
          <CardContent className="p-4 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-6 w-full skeleton-shimmer rounded" />
            ))}
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!data || data.rows.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold text-foreground">Actions</h1>
        <p className="text-muted-foreground text-sm">
          {emptyStateMessage ?? "No action data."}{" "}
          <br />
          Run the pipeline first:{" "}
          <code className="text-foreground/60 bg-muted px-1.5 py-0.5 rounded text-xs">python -m pipeline.cli run</code>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-4 flex-wrap animate-fade-in-up">
        <div>
          <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
            <Zap className="h-5 w-5 text-warning" /> Monthly Actions
          </h1>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <p className="text-muted-foreground text-sm">
              Rebalance date: {data.run_date ? fmtDate(data.run_date) : "—"}
            </p>
            <Badge variant="outline" className={regimeBadgeClass(data.macro_regime)}>
              {regimeLabel(data.macro_regime)}
            </Badge>
            {data.shock_regime && (
              <Badge variant="outline" className="border-negative/50 bg-negative/10 text-negative">
                Shock Regime
              </Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs border-border text-foreground/70 gap-1.5 btn-scale cursor-pointer"
            onClick={handleRefreshPrices}
            disabled={refreshing}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            Refresh prices
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs border-border text-muted-foreground gap-1.5 hover:border-warning hover:text-warning btn-scale cursor-pointer"
            onClick={() => setSkipOpen(true)}
          >
            <SkipForward className="h-3.5 w-3.5" />
            Skip this month
          </Button>
        </div>
      </div>

      {data.shock_regime && (
        <Card className="bg-negative/5 border-negative/20 animate-fade-in-up">
          <CardContent className="px-4 py-3 text-sm text-negative">
            Shock regime is active. Pause new buys for the rest of the month. Do not sell existing
            holdings on the banner alone.
          </CardContent>
        </Card>
      )}

      <Card className="bg-card border-border border-l-2 border-l-primary animate-fade-in-up stagger-2">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-foreground">
            Capital Deployment Planner
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-1">
            Executed {executedCount} of {actionableCount} trade actions.
          </p>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="flex items-center gap-4">
              <span className="text-xs text-muted-foreground w-32 shrink-0">Fresh capital</span>
              <input
                type="number"
                value={freshCapital}
                onChange={(event) => setFreshCapital(Number(event.target.value))}
                className="w-36 h-8 rounded-md bg-muted border border-border text-foreground text-sm px-3 font-mono focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                step={1000}
                min={0}
              />
            </label>
            <label className="flex items-center gap-4">
              <span className="text-xs text-muted-foreground w-32 shrink-0">SELL proceeds</span>
              <input
                type="number"
                value={sellProceeds}
                onChange={(event) => setSellProceeds(Number(event.target.value))}
                className="w-36 h-8 rounded-md bg-muted border border-border text-foreground text-sm px-3 font-mono focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                step={1000}
                min={0}
              />
            </label>
          </div>

          <div className="space-y-3">
            {BUCKET_ORDER.map((bucket) => {
              const pct = alloc[bucket];
              const amount = Math.round((pct / 100) * (freshCapital + sellProceeds));
              return (
                <div key={bucket} className="flex items-center gap-4">
                  <span className="text-xs text-muted-foreground w-40 shrink-0">{bucketLabel(bucket)}</span>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={[pct]}
                    onValueChange={(values) => {
                      const next = Array.isArray(values) ? values[0] : values;
                      setAlloc((current) => ({ ...current, [bucket]: next ?? pct }));
                    }}
                    className="flex-1"
                  />
                  <span className="text-xs font-mono text-foreground/80 w-10 text-right">{pct}%</span>
                  <span className="text-xs font-mono text-muted-foreground w-20 text-right">
                    {fmtINR(amount)}
                  </span>
                </div>
              );
            })}
            {totalAllocPct !== 100 && (
              <p className="text-xs text-warning">
                Allocations sum to {totalAllocPct}% and should add up to 100%.
              </p>
            )}
            {data.plan && (
              <div className="flex items-center gap-4 flex-wrap text-xs text-muted-foreground pt-2">
                <span>Total available: {fmtINR(data.plan.total)}</span>
                <span>Undeployed: {fmtINR(data.plan.undeployed)}</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card className="bg-card border-border overflow-hidden animate-fade-in-up stagger-3">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-foreground">Action Table</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left px-4 py-2.5 font-normal">Ticker</th>
                  <th className="text-left px-4 py-2.5 font-normal">Bucket</th>
                  <th className="text-right px-4 py-2.5 font-normal">Action</th>
                  <th className="text-right px-4 py-2.5 font-normal">Score</th>
                  <th className="text-right px-4 py-2.5 font-normal">Current</th>
                  <th className="text-right px-4 py-2.5 font-normal">Suggest</th>
                  <th className="text-left px-4 py-2.5 font-normal">Reason</th>
                  <th className="text-center px-4 py-2.5 font-normal">Done</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => {
                  const livePrice = livePrices[row.ticker];
                  const displayPrice = livePrice ?? row.current_price;
                  const displayQty =
                    row.suggested_amount != null && displayPrice != null && displayPrice > 0
                      ? row.suggested_amount / displayPrice
                      : row.suggested_qty;
                  const isHold = normalizeAction(row.action) === "hold";

                  return (
                    <tr
                      key={`${row.ticker}-${row.bucket}`}
                      className={`border-b border-border/40 last:border-0 transition-colors duration-150 ${
                        row.executed ? "opacity-50" : "hover:bg-accent/50"
                      }`}
                    >
                      <td className="px-4 py-2.5">
                        <a
                          href={`/stocks/${row.ticker}`}
                          className="text-primary hover:text-primary/80 font-mono font-medium transition-colors cursor-pointer"
                        >
                          {row.ticker}
                        </a>
                        <span className="ml-1 text-muted-foreground">{countryFlag(row.country)}</span>
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground">{bucketLabel(row.bucket)}</td>
                      <td className={`px-4 py-2.5 text-right font-semibold ${actionColor(row.action)}`}>
                        {actionLabel(row.action)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                        {fmtNum(row.score, 1)}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-foreground/80">
                        {displayPrice != null ? fmtNum(displayPrice, 2) : "—"}
                        {livePrice != null && (
                          <Badge
                            variant="outline"
                            className="ml-1 text-[10px] border-positive/50 text-positive px-1 py-0"
                          >
                            live
                          </Badge>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-muted-foreground">
                        {row.suggested_amount != null ? (
                          <div>
                            <div>{fmtINR(row.suggested_amount)}</div>
                            {displayQty != null && (
                              <div className="text-[10px] text-muted-foreground">{fmtNum(displayQty, 2)} qty</div>
                            )}
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground max-w-sm">
                        <p className="truncate" title={row.reason}>
                          {row.reason}
                        </p>
                      </td>
                      <td className="px-4 py-2.5 text-center">
                        {!isHold && (
                          <button
                            onClick={() => openExecuteDialog(row)}
                            disabled={row.executed}
                            className={`transition-all duration-200 cursor-pointer ${
                              row.executed ? "text-positive scale-110" : "text-muted-foreground hover:text-positive hover:scale-110"
                            }`}
                            title={row.executed ? "Executed" : "Mark as executed"}
                          >
                            <CheckSquare className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={skipOpen} onOpenChange={setSkipOpen}>
        <DialogContent className="bg-card border-border text-foreground">
          <DialogHeader>
            <DialogTitle className="text-foreground">Skip This Month</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This logs a deliberate no-trade month in the journal. The rule still applies: pause new
            buys when conditions are unclear, but do not sell existing holdings because of a banner alone.
          </p>
          <textarea
            value={skipReason}
            onChange={(event) => setSkipReason(event.target.value)}
            placeholder="Why are you skipping this month? (required)"
            rows={3}
            className="w-full rounded-md bg-muted border border-border text-foreground text-sm px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" className="text-muted-foreground cursor-pointer" onClick={() => setSkipOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="bg-warning text-warning-foreground hover:bg-warning/90 btn-scale cursor-pointer"
              onClick={handleSkip}
              disabled={!skipReason.trim()}
            >
              Confirm skip
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={executeRow != null}
        onOpenChange={(open) => {
          if (!open) setExecuteRow(null);
        }}
      >
        <DialogContent className="bg-card border-border text-foreground">
          <DialogHeader>
            <DialogTitle>
              {executeRow ? `${actionLabel(executeRow.action)} ${executeRow.ticker}` : "Execute trade"}
            </DialogTitle>
          </DialogHeader>
          {executeRow && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {bucketLabel(executeRow.bucket)} · {countryFlag(executeRow.country)}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">Actual fill price</span>
                  <input
                    type="number"
                    value={fillPrice}
                    onChange={(event) => setFillPrice(event.target.value)}
                    className="w-full h-9 rounded-md bg-muted border border-border text-foreground text-sm px-3 focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">Quantity</span>
                  <input
                    type="number"
                    value={qty}
                    onChange={(event) => setQty(event.target.value)}
                    className="w-full h-9 rounded-md bg-muted border border-border text-foreground text-sm px-3 focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                  />
                </label>
              </div>
              <label className="space-y-1 block">
                <span className="text-xs text-muted-foreground">Notes</span>
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={2}
                  className="w-full rounded-md bg-muted border border-border text-foreground text-sm px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                />
              </label>
              {["sell", "trim"].includes(normalizeAction(executeRow.action)) && (
                <label className="space-y-1 block">
                  <span className="text-xs text-primary">What did you learn?</span>
                  <textarea
                    value={lesson}
                    onChange={(event) => setLesson(event.target.value)}
                    rows={2}
                    placeholder="Required for exits."
                    className="w-full rounded-md bg-muted border border-primary/30 text-foreground text-sm px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                  />
                </label>
              )}
              {actionError && <p className="text-sm text-negative">{actionError}</p>}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" className="text-muted-foreground cursor-pointer" onClick={() => setExecuteRow(null)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="bg-primary text-primary-foreground hover:bg-primary/90 btn-scale cursor-pointer"
                  onClick={handleExecute}
                  disabled={submitting}
                >
                  {submitting ? "Saving…" : "Mark executed"}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

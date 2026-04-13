"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { api, BucketList, RankedStock } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fmtNum,
  fmtDate,
  bucketLabel,
  bucketColor,
  actionColor,
} from "@/lib/format";
import { ChevronDown, Filter } from "lucide-react";

const RANKED_COUNTRY = "IN" as const;

const BUCKETS = [
  { value: "quality_value", label: "Quality + Value" },
  { value: "momentum", label: "Momentum" },
  { value: "quality_momentum", label: "Quality + Momentum" },
  { value: "dividend_growth", label: "Dividend Growth" },
];

const SORTS = [
  { value: "", label: "Score (default)" },
  { value: "pe_asc", label: "P/E Low → High" },
  { value: "pe_desc", label: "P/E High → Low" },
  { value: "pb_asc", label: "P/B Low → High" },
  { value: "pb_desc", label: "P/B High → Low" },
];

export default function RankedPage() {
  const [lists, setLists] = useState<BucketList[]>([]);
  const [runDate, setRunDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [bucket, setBucket] = useState("");
  const [sort, setSort] = useState("");
  const [picks, setPicks] = useState(10);

  // Expanded state per list key
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    api
      .ranked({
        bucket: bucket || undefined,
        country: RANKED_COUNTRY,
        pe_sort: sort.startsWith("pe") ? sort : undefined,
        pb_sort: sort.startsWith("pb") ? sort : undefined,
        picks,
      })
      .then((r) => {
        const indiaLists = r.lists.filter((list) => list.country === RANKED_COUNTRY);
        console.log(`[Ranked] received run_date=${r.run_date} lists=${indiaLists.length}`);
        indiaLists.forEach((l) =>
          console.log(`[Ranked]   ${l.bucket}/${l.country} actionable=${l.actionable.length} extended=${l.extended.length}`)
        );
        setLists(indiaLists);
        setRunDate(r.run_date);
      })
      .catch((err) => console.error("[Ranked] fetch error:", err))
      .finally(() => setLoading(false));
  }, [bucket, sort, picks]);

  useEffect(() => {
    load();
  }, [load]);

  function toggleExpanded(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function handleBucketChange(value: string | null) {
    setLoading(true);
    setBucket(value ?? "");
  }

  function handleSortChange(value: string | null) {
    setLoading(true);
    setSort(value ?? "");
  }

  function handlePicksChange(value: string | null) {
    setLoading(true);
    setPicks(Number(value ?? picks));
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap animate-fade-in-up">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Ranked Lists</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            {runDate ? `Last rebalance run: ${fmtDate(runDate)}` : "No rebalance data yet — run the pipeline first."}
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap animate-fade-in-up stagger-2">
        <Filter className="h-4 w-4 text-muted-foreground shrink-0" />
        <Select value={bucket} onValueChange={handleBucketChange}>
          <SelectTrigger className="w-48 h-8 text-xs bg-card border-border cursor-pointer">
            <SelectValue placeholder="All buckets" />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            <SelectItem value="" className="text-xs cursor-pointer">All buckets</SelectItem>
            {BUCKETS.map((b) => (
              <SelectItem key={b.value} value={b.value} className="text-xs cursor-pointer">
                {b.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Badge variant="secondary" className="h-8 px-3 text-xs font-medium">
          India only
        </Badge>

        <Select value={sort} onValueChange={handleSortChange}>
          <SelectTrigger className="w-44 h-8 text-xs bg-card border-border cursor-pointer">
            <SelectValue placeholder="Sort: Score" />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            {SORTS.map((s) => (
              <SelectItem key={s.value} value={s.value} className="text-xs cursor-pointer">
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={String(picks)} onValueChange={handlePicksChange}>
          <SelectTrigger className="w-28 h-8 text-xs bg-card border-border cursor-pointer">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            {[5, 10, 15, 20].map((n) => (
              <SelectItem key={n} value={String(n)} className="text-xs cursor-pointer">
                Top {n}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {Array.from({ length: 2 }).map((_, i) => (
            <Card key={i} className="bg-card border-border">
              <CardHeader className="px-4 pt-4 pb-3">
                <div className="h-4 w-40 skeleton-shimmer rounded" />
              </CardHeader>
              <CardContent className="p-4 space-y-2">
                {Array.from({ length: 5 }).map((_, j) => (
                  <div key={j} className="h-6 w-full skeleton-shimmer rounded" />
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {!loading && lists.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No India ranked data. Run the pipeline first: <code className="text-foreground/60 bg-muted px-1.5 py-0.5 rounded text-xs">python -m pipeline.cli run</code>
        </p>
      )}

      {/* Lists grid */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {lists.map((list, i) => {
          const key = `${list.bucket}-${list.country}`;
          const isExpanded = expanded.has(key);
          return (
            <div key={key} className="animate-fade-in-up" style={{ animationDelay: `${i * 100}ms` }}>
              <BucketListCard
                list={list}
                isExpanded={isExpanded}
                onToggleExpand={() => toggleExpanded(key)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BucketListCard({
  list,
  isExpanded,
  onToggleExpand,
}: {
  list: BucketList;
  isExpanded: boolean;
  onToggleExpand: () => void;
}) {
  const colorDot = bucketColor(list.bucket);
  const allVisible = isExpanded
    ? [...list.actionable, ...list.extended]
    : list.actionable;

  return (
    <Card className="bg-card border-border overflow-hidden">
      <CardHeader className="px-4 pt-4 pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${colorDot}`} />
            {bucketLabel(list.bucket)}
            <span className="text-muted-foreground font-normal">
              India
            </span>
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {list.showing} / {list.total} shown
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="text-left px-4 py-2 font-normal w-6">#</th>
                <th className="text-left px-4 py-2 font-normal">Ticker</th>
                <th className="text-right px-4 py-2 font-normal">Score</th>
                <th className="text-right px-4 py-2 font-normal">P/E</th>
                <th className="text-right px-4 py-2 font-normal">P/B</th>
                <th className="text-right px-4 py-2 font-normal">Action</th>
              </tr>
            </thead>
            <tbody>
              {allVisible.map((stock) => (
                <StockRow key={stock.ticker} stock={stock} />
              ))}
            </tbody>
          </table>
        </div>

        {list.extended.length > 0 && (
          <div className="border-t border-border px-4 py-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-muted-foreground hover:text-foreground gap-1 cursor-pointer"
              onClick={onToggleExpand}
            >
              <span
                className={`inline-block transition-transform duration-200 ${isExpanded ? "rotate-180" : ""}`}
              >
                <ChevronDown className="h-3 w-3" />
              </span>
              {isExpanded ? "Show less" : `Show ${list.extended.length} more`}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StockRow({ stock }: { stock: RankedStock }) {
  const isGrayed = !stock.is_actionable;
  return (
    <tr
      className={`border-b border-border/40 last:border-0 hover:bg-accent/50 transition-colors duration-150 ${
        isGrayed ? "opacity-50" : ""
      }`}
    >
      <td className="px-4 py-2 text-muted-foreground">{stock.rank}</td>
      <td className="px-4 py-2">
        <Link
          href={`/stocks/${stock.ticker}`}
          className="text-primary hover:text-primary/80 font-mono font-medium transition-colors cursor-pointer"
        >
          {stock.ticker}
        </Link>
        {stock.sector && (
          <span className="ml-1.5 text-muted-foreground truncate max-w-24 inline-block align-middle">
            {stock.sector}
          </span>
        )}
      </td>
      <td className="px-4 py-2 text-right font-mono text-foreground">
        {fmtNum(stock.score, 1)}
      </td>
      <td className="px-4 py-2 text-right font-mono text-muted-foreground">
        {stock.pe_ratio != null ? fmtNum(stock.pe_ratio, 1) : "—"}
      </td>
      <td className="px-4 py-2 text-right font-mono text-muted-foreground">
        {stock.pb_ratio != null ? fmtNum(stock.pb_ratio, 1) : "—"}
      </td>
      <td className={`px-4 py-2 text-right font-semibold ${stock.action ? actionColor(stock.action) : "text-muted-foreground"}`}>
        {stock.action ?? "—"}
      </td>
    </tr>
  );
}

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
  countryFlag,
} from "@/lib/format";
import { ChevronDown, ChevronUp, Filter } from "lucide-react";

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
  const [country, setCountry] = useState("");
  const [sort, setSort] = useState("");
  const [picks, setPicks] = useState(10);

  // Expanded state per list key
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setLoading(true);
    api
      .ranked({
        bucket: bucket || undefined,
        country: country || undefined,
        pe_sort: sort.startsWith("pe") ? sort : undefined,
        pb_sort: sort.startsWith("pb") ? sort : undefined,
        picks,
      })
      .then((r) => {
        console.log(`[Ranked] received run_date=${r.run_date} lists=${r.lists.length}`);
        r.lists.forEach((l) =>
          console.log(`[Ranked]   ${l.bucket}/${l.country} actionable=${l.actionable.length} extended=${l.extended.length}`)
        );
        setLists(r.lists);
        setRunDate(r.run_date);
      })
      .catch((err) => console.error("[Ranked] fetch error:", err))
      .finally(() => setLoading(false));
  }, [bucket, country, sort, picks]);

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

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Ranked Lists</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {runDate ? `Last rebalance run: ${fmtDate(runDate)}` : "No rebalance data yet — run the pipeline first."}
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="h-4 w-4 text-slate-500 shrink-0" />
        <Select value={bucket} onValueChange={(v) => setBucket(v ?? "")}>
          <SelectTrigger className="w-48 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue placeholder="All buckets" />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            <SelectItem value="" className="text-xs">All buckets</SelectItem>
            {BUCKETS.map((b) => (
              <SelectItem key={b.value} value={b.value} className="text-xs">
                {b.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={country} onValueChange={(v) => setCountry(v ?? "")}>
          <SelectTrigger className="w-36 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue placeholder="Both markets" />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            <SelectItem value="" className="text-xs">Both markets</SelectItem>
            <SelectItem value="IN" className="text-xs">🇮🇳 India only</SelectItem>
            <SelectItem value="US" className="text-xs">🇺🇸 US only</SelectItem>
          </SelectContent>
        </Select>

        <Select value={sort} onValueChange={(v) => setSort(v ?? "")}>
          <SelectTrigger className="w-44 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue placeholder="Sort: Score" />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            {SORTS.map((s) => (
              <SelectItem key={s.value} value={s.value} className="text-xs">
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={String(picks)} onValueChange={(v) => setPicks(Number(v ?? picks))}>
          <SelectTrigger className="w-28 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            {[5, 10, 15, 20].map((n) => (
              <SelectItem key={n} value={String(n)} className="text-xs">
                Top {n}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading && <p className="text-slate-500 text-sm">Loading…</p>}

      {!loading && lists.length === 0 && (
        <p className="text-slate-500 text-sm">
          No ranked data. Run the pipeline first: <code className="text-slate-400">python -m pipeline.cli run</code>
        </p>
      )}

      {/* Lists grid */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {lists.map((list) => {
          const key = `${list.bucket}-${list.country}`;
          const isExpanded = expanded.has(key);
          return (
            <BucketListCard
              key={key}
              list={list}
              isExpanded={isExpanded}
              onToggleExpand={() => toggleExpanded(key)}
            />
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
    <Card className="bg-slate-900 border-slate-800">
      <CardHeader className="px-4 pt-4 pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <span className={`inline-block w-2 h-2 rounded-full ${colorDot}`} />
            {bucketLabel(list.bucket)}
            <span className="text-slate-500 font-normal">
              {countryFlag(list.country)} {list.country === "IN" ? "India" : "US"}
            </span>
          </CardTitle>
          <span className="text-xs text-slate-600">
            {list.showing} / {list.total} shown
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-600">
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

        {list.extended.length > 0 && (
          <div className="border-t border-slate-800 px-4 py-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-slate-500 hover:text-slate-300 gap-1"
              onClick={onToggleExpand}
            >
              {isExpanded ? (
                <>
                  <ChevronUp className="h-3 w-3" /> Show less
                </>
              ) : (
                <>
                  <ChevronDown className="h-3 w-3" /> Show {list.extended.length} more
                </>
              )}
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
      className={`border-b border-slate-800/40 last:border-0 hover:bg-slate-800/30 transition-colors ${
        isGrayed ? "opacity-50" : ""
      }`}
    >
      <td className="px-4 py-2 text-slate-600">{stock.rank}</td>
      <td className="px-4 py-2">
        <Link
          href={`/stocks/${stock.ticker}`}
          className="text-indigo-400 hover:text-indigo-300 font-mono font-medium"
        >
          {stock.ticker}
        </Link>
        {stock.sector && (
          <span className="ml-1.5 text-slate-600 truncate max-w-24 inline-block align-middle">
            {stock.sector}
          </span>
        )}
      </td>
      <td className="px-4 py-2 text-right font-mono text-slate-200">
        {fmtNum(stock.score, 1)}
      </td>
      <td className="px-4 py-2 text-right font-mono text-slate-400">
        {stock.pe_ratio != null ? fmtNum(stock.pe_ratio, 1) : "—"}
      </td>
      <td className="px-4 py-2 text-right font-mono text-slate-400">
        {stock.pb_ratio != null ? fmtNum(stock.pb_ratio, 1) : "—"}
      </td>
      <td className={`px-4 py-2 text-right font-semibold ${stock.action ? actionColor(stock.action) : "text-slate-600"}`}>
        {stock.action ?? "—"}
      </td>
    </tr>
  );
}

"use client";

import { useEffect, useState, useCallback } from "react";
import { api, NewsArticle } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fmtDate, sentimentColor } from "@/lib/format";
import { Newspaper } from "lucide-react";

const CATEGORIES = ["Earnings", "Management", "Regulatory", "M&A", "Dividend", "Other"];

export default function NewsPage() {
  const [items, setItems] = useState<NewsArticle[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("");
  const [stream, setStream] = useState("stock");
  const [offset, setOffset] = useState(0);

  const LIMIT = 30;

  const load = useCallback(
    (newOffset = 0) => {
      setLoading(true);
      api
        .news({
          category: category || undefined,
          stream: stream || undefined,
          limit: LIMIT,
          offset: newOffset,
        })
        .then((r) => {
          const incoming = r.items ?? [];
          setItems(newOffset === 0 ? incoming : (prev) => [...prev, ...incoming]);
          setTotal(r.total ?? 0);
          setOffset(newOffset + incoming.length);
        })
        .finally(() => setLoading(false));
    },
    [category, stream]
  );

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold text-slate-100 flex items-center gap-2">
          <Newspaper className="h-5 w-5 text-indigo-400" /> News Feed
        </h1>
        <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
          News informs your next 7th-of-month decision. It does not trigger an immediate trade.
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={stream} onValueChange={(v) => setStream(v ?? "stock")}>
          <SelectTrigger className="w-36 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            <SelectItem value="stock" className="text-xs">Stock news</SelectItem>
            <SelectItem value="general" className="text-xs">Market shocks</SelectItem>
          </SelectContent>
        </Select>

        <Select value={category} onValueChange={(v) => setCategory(v ?? "")}>
          <SelectTrigger className="w-40 h-8 text-xs bg-slate-900 border-slate-700">
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent className="bg-slate-900 border-slate-700">
            <SelectItem value="" className="text-xs">All categories</SelectItem>
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">{c}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <span className="text-xs text-slate-600 ml-auto">{total} articles</span>
      </div>

      {/* News items */}
      <div className="space-y-0">
        {loading && items.length === 0 && (
          <p className="text-slate-500 text-sm">Loading…</p>
        )}
        {!loading && items.length === 0 && (
          <p className="text-slate-600 text-sm">No news found.</p>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-start gap-3 py-3 border-b border-slate-800/60 last:border-0"
          >
            <span className={`mt-0.5 text-sm font-bold shrink-0 w-4 text-center ${sentimentColor(item.sentiment)}`}>
              {item.sentiment === "positive" ? "+" : item.sentiment === "negative" ? "−" : "·"}
            </span>
            <div className="flex-1 min-w-0">
              {item.url ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-slate-200 hover:text-indigo-300 line-clamp-2 leading-snug"
                >
                  {item.headline}
                </a>
              ) : (
                <p className="text-sm text-slate-200 line-clamp-2 leading-snug">{item.headline}</p>
              )}
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                {item.ticker && (
                  <a href={`/stocks/${item.ticker}`} className="text-xs text-indigo-400 font-mono hover:text-indigo-300">
                    {item.ticker}
                  </a>
                )}
                {item.category && (
                  <Badge variant="outline" className="text-xs border-slate-700 text-slate-500 px-1.5 py-0">
                    {item.category}
                  </Badge>
                )}
                <span className="text-xs text-slate-600">
                  {item.source} · {fmtDate(item.published_at)}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Load more */}
      {offset < total && (
        <Button
          variant="outline"
          size="sm"
          className="w-full h-8 text-xs border-slate-700 text-slate-400"
          onClick={() => load(offset)}
          disabled={loading}
        >
          Load more ({total - offset} remaining)
        </Button>
      )}
    </div>
  );
}

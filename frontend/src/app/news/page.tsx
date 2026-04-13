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

const CATEGORIES = [
  { value: "earnings", label: "Earnings" },
  { value: "management", label: "Management" },
  { value: "regulatory", label: "Regulatory" },
  { value: "m_and_a", label: "M&A" },
  { value: "dividend", label: "Dividend" },
  { value: "other", label: "Other" },
];

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
          console.log(`[News] received total=${r.total} incoming=${incoming.length} offset=${newOffset} category=${category || "all"} stream=${stream}`);
          setItems(newOffset === 0 ? incoming : (prev) => [...prev, ...incoming]);
          setTotal(r.total ?? 0);
          setOffset(newOffset + incoming.length);
        })
        .catch((err) => console.error("[News] fetch error:", err))
        .finally(() => setLoading(false));
    },
    [category, stream]
  );

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="animate-fade-in-up">
        <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
          <Newspaper className="h-5 w-5 text-primary" /> News Feed
        </h1>
        <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
          News informs your next 7th-of-month decision. It does not trigger an immediate trade.
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap animate-fade-in-up stagger-2">
        <Select value={stream} onValueChange={(v) => setStream(v ?? "stock")}>
          <SelectTrigger className="w-36 h-8 text-xs bg-card border-border cursor-pointer">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            <SelectItem value="stock" className="text-xs cursor-pointer">Stock news</SelectItem>
            <SelectItem value="general" className="text-xs cursor-pointer">Market shocks</SelectItem>
          </SelectContent>
        </Select>

        <Select value={category} onValueChange={(v) => setCategory(v ?? "")}>
          <SelectTrigger className="w-40 h-8 text-xs bg-card border-border cursor-pointer">
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent className="bg-card border-border">
            <SelectItem value="" className="text-xs cursor-pointer">All categories</SelectItem>
            {CATEGORIES.map((categoryOption) => (
              <SelectItem key={categoryOption.value} value={categoryOption.value} className="text-xs cursor-pointer">
                {categoryOption.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <span className="text-xs text-muted-foreground ml-auto">{total} articles</span>
      </div>

      {/* News items */}
      <div className="space-y-0">
        {loading && items.length === 0 && (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex gap-3 py-3">
                <div className="h-4 w-4 skeleton-shimmer rounded-full shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-3/4 skeleton-shimmer rounded" />
                  <div className="h-3 w-1/3 skeleton-shimmer rounded" />
                </div>
              </div>
            ))}
          </div>
        )}
        {!loading && items.length === 0 && (
          <p className="text-muted-foreground text-sm">No news found.</p>
        )}
        {items.map((item, i) => (
          <div
            key={item.id}
            className="flex items-start gap-3 py-3 border-b border-border/60 last:border-0 hover:bg-accent/30 transition-colors duration-150 rounded-sm px-1 -mx-1 animate-fade-in-up"
            style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}
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
                  className="text-sm text-foreground hover:text-primary line-clamp-2 leading-snug transition-colors cursor-pointer"
                >
                  {item.headline}
                </a>
              ) : (
                <p className="text-sm text-foreground line-clamp-2 leading-snug">{item.headline}</p>
              )}
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                {item.ticker && (
                  <a href={`/stocks/${item.ticker}`} className="text-xs text-primary font-mono hover:text-primary/80 transition-colors cursor-pointer">
                    {item.ticker}
                  </a>
                )}
                {item.category && (
                  <Badge variant="outline" className="text-xs border-border text-muted-foreground px-1.5 py-0">
                    {item.category.replaceAll("_", " ")}
                  </Badge>
                )}
                <span className="text-xs text-muted-foreground">
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
          className="w-full h-8 text-xs border-border text-muted-foreground btn-scale cursor-pointer"
          onClick={() => load(offset)}
          disabled={loading}
        >
          Load more ({total - offset} remaining)
        </Button>
      )}
    </div>
  );
}

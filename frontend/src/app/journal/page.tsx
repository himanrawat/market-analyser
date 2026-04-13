"use client";

import { useEffect, useState } from "react";
import { api, JournalEntry, MonthlyReview } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtNum, fmtDate, bucketLabel, actionColor } from "@/lib/format";
import { BookOpen } from "lucide-react";

function normalizeAction(action: string) {
  return action.toLowerCase();
}

function actionLabel(action: string) {
  return normalizeAction(action).replace("_", " ").toUpperCase();
}

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [reviews, setReviews] = useState<MonthlyReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [editId, setEditId] = useState<number | null>(null);
  const [editFill, setEditFill] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editLesson, setEditLesson] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [journalEntries, monthlyReviews] = await Promise.all([
      api.journal({ limit: 100 }),
      api.journalReview(6),
    ]);
    setEntries(journalEntries);
    setReviews(monthlyReviews);
  }

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, []);

  async function handleSave(entry: JournalEntry) {
    if (
      ["sell", "trim"].includes(normalizeAction(entry.action_type)) &&
      !editLesson.trim()
    ) {
      setError("Exit actions require a short lesson.");
      return;
    }

    setError(null);
    await api.updateJournal(entry.id, {
      fill_price: editFill ? Number(editFill) : undefined,
      notes: editNotes || undefined,
      lesson: editLesson || undefined,
    });
    setEditId(null);
    await load();
  }

  function startEdit(entry: JournalEntry) {
    setEditId(entry.id);
    setEditFill(entry.fill_price != null ? String(entry.fill_price) : "");
    setEditNotes(entry.notes ?? "");
    setEditLesson(entry.lesson ?? "");
    setError(null);
  }

  if (loading) {
    return (
      <div className="space-y-4 max-w-5xl">
        <div className="h-6 w-36 skeleton-shimmer rounded" />
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-20 w-full skeleton-shimmer rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="animate-fade-in-up">
        <h1 className="text-xl font-semibold text-foreground flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-primary" /> Trade Journal
        </h1>
        <p className="text-muted-foreground text-sm mt-0.5">{entries.length} entries</p>
      </div>

      <Tabs defaultValue="entries">
        <TabsList className="bg-card border-b border-border rounded-none h-auto p-0 justify-start gap-0">
          {["entries", "review"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary text-muted-foreground text-xs px-4 py-2.5 capitalize cursor-pointer transition-colors"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="entries" className="mt-4 space-y-2">
          {entries.length === 0 && (
            <p className="text-muted-foreground text-sm">
              No journal entries yet. Execute actions on the Actions screen to create entries.
            </p>
          )}
          {entries.map((entry, i) => {
            const isExit = ["sell", "trim"].includes(normalizeAction(entry.action_type));
            return (
              <Card key={entry.id} className="bg-card border-border animate-fade-in-up" style={{ animationDelay: `${i * 30}ms` }}>
                <CardContent className="px-4 py-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3 flex-wrap">
                      {entry.ticker ? (
                        <a
                          href={`/stocks/${entry.ticker}`}
                          className="font-mono font-semibold text-primary hover:text-primary/80 transition-colors cursor-pointer"
                        >
                          {entry.ticker}
                        </a>
                      ) : (
                        <span className="font-medium text-foreground/80">No ticker</span>
                      )}
                      {entry.skipped_month ? (
                        <Badge variant="outline" className="border-warning/50 text-warning text-xs">
                          SKIPPED MONTH
                        </Badge>
                      ) : (
                        <span className={`text-sm font-semibold ${actionColor(entry.action_type)}`}>
                          {actionLabel(entry.action_type)}
                        </span>
                      )}
                      {entry.bucket && (
                        <span className="text-xs text-muted-foreground">{bucketLabel(entry.bucket)}</span>
                      )}
                      <span className="text-xs text-muted-foreground">{fmtDate(entry.action_date)}</span>
                    </div>
                    <button
                      onClick={() => (editId === entry.id ? setEditId(null) : startEdit(entry))}
                      className="text-xs text-muted-foreground hover:text-foreground shrink-0 cursor-pointer transition-colors"
                    >
                      {editId === entry.id ? "Cancel" : "Edit"}
                    </button>
                  </div>

                  {entry.thesis && (
                    <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">{entry.thesis}</p>
                  )}

                  <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground flex-wrap">
                    {entry.suggested_price != null && (
                      <span>
                        Suggested:{" "}
                        <span className="font-mono text-foreground/60">
                          {fmtNum(entry.suggested_price, 2)}
                        </span>
                      </span>
                    )}
                    {entry.fill_price != null && (
                      <span>
                        Fill:{" "}
                        <span className="font-mono text-foreground/70">{fmtNum(entry.fill_price, 2)}</span>
                      </span>
                    )}
                    {entry.qty != null && (
                      <span>
                        Qty: <span className="font-mono text-foreground/70">{entry.qty}</span>
                      </span>
                    )}
                  </div>

                  {entry.notes && (
                    <p className="text-xs text-muted-foreground mt-1.5 italic">{entry.notes}</p>
                  )}
                  {entry.lesson && (
                    <p className="text-xs text-primary mt-1 italic">&ldquo;{entry.lesson}&rdquo;</p>
                  )}

                  {editId === entry.id && (
                    <div className="mt-3 space-y-2 border-t border-border pt-3 animate-scale-in">
                      <div className="flex items-center gap-3">
                        <label className="text-xs text-muted-foreground w-20 shrink-0">Fill price</label>
                        <input
                          type="number"
                          value={editFill}
                          onChange={(event) => setEditFill(event.target.value)}
                          className="h-7 w-32 rounded bg-muted border border-border text-foreground text-xs px-2 font-mono focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                        />
                      </div>
                      <div className="flex items-start gap-3">
                        <label className="text-xs text-muted-foreground w-20 shrink-0 mt-1">Notes</label>
                        <textarea
                          value={editNotes}
                          onChange={(event) => setEditNotes(event.target.value)}
                          rows={2}
                          className="flex-1 rounded bg-muted border border-border text-foreground text-xs px-2 py-1 resize-none focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                        />
                      </div>
                      {isExit && (
                        <div className="flex items-start gap-3">
                          <label className="text-xs text-primary w-20 shrink-0 mt-1">
                            Lesson
                          </label>
                          <textarea
                            value={editLesson}
                            onChange={(event) => setEditLesson(event.target.value)}
                            rows={2}
                            placeholder="Required for exits."
                            className="flex-1 rounded bg-muted border border-primary/30 text-foreground text-xs px-2 py-1 resize-none focus:outline-none focus:ring-1 focus:ring-primary transition-shadow"
                          />
                        </div>
                      )}
                      {error && <p className="text-xs text-negative">{error}</p>}
                      <div className="flex justify-end">
                        <button
                          onClick={() => handleSave(entry)}
                          className="text-xs bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-1 rounded btn-scale cursor-pointer transition-colors"
                        >
                          Save
                        </button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </TabsContent>

        <TabsContent value="review" className="mt-4 space-y-4">
          {reviews.length === 0 ? (
            <p className="text-muted-foreground text-sm">No review data yet.</p>
          ) : (
            reviews.map((review, i) => (
              <Card key={review.month} className="bg-card border-border animate-fade-in-up" style={{ animationDelay: `${i * 80}ms` }}>
                <CardHeader className="px-4 pt-4 pb-2">
                  <CardTitle className="text-sm text-foreground">{review.month}</CardTitle>
                </CardHeader>
                <CardContent className="px-4 pb-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                      { label: "Trades", value: String(review.total_trades) },
                      { label: "Buys", value: String(review.buys) },
                      { label: "Sells", value: String(review.sells) },
                      {
                        label: "Win Rate",
                        value: review.win_rate != null ? `${fmtNum(review.win_rate, 0)}%` : "—",
                      },
                      {
                        label: "Avg Hold",
                        value:
                          review.avg_holding_days != null
                            ? `${fmtNum(review.avg_holding_days, 0)}d`
                            : "—",
                      },
                      {
                        label: "Biggest Winner",
                        value:
                          review.biggest_winner && review.biggest_winner_pct != null
                            ? `${review.biggest_winner} (${fmtNum(review.biggest_winner_pct, 1)}%)`
                            : review.biggest_winner ?? "—",
                      },
                      {
                        label: "Biggest Loser",
                        value:
                          review.biggest_loser && review.biggest_loser_pct != null
                            ? `${review.biggest_loser} (${fmtNum(review.biggest_loser_pct, 1)}%)`
                            : review.biggest_loser ?? "—",
                      },
                      { label: "Lessons Logged", value: String(review.lessons_logged) },
                    ].map(({ label, value }) => (
                      <div key={label} className="rounded-lg border border-border bg-muted/30 px-3 py-3 card-hover">
                        <p className="text-xs text-muted-foreground">{label}</p>
                        <p className="text-sm font-mono text-foreground mt-1">{value}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

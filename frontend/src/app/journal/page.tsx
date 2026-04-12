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

  if (loading) return <p className="text-slate-500 text-sm">Loading journal…</p>;

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold text-slate-100 flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-indigo-400" /> Trade Journal
        </h1>
        <p className="text-slate-500 text-sm mt-0.5">{entries.length} entries</p>
      </div>

      <Tabs defaultValue="entries">
        <TabsList className="bg-slate-900 border-b border-slate-800 rounded-none h-auto p-0 justify-start gap-0">
          {["entries", "review"].map((tab) => (
            <TabsTrigger
              key={tab}
              value={tab}
              className="rounded-none border-b-2 border-transparent data-[state=active]:border-indigo-500 data-[state=active]:bg-transparent data-[state=active]:text-indigo-300 text-slate-500 text-xs px-4 py-2.5 capitalize"
            >
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="entries" className="mt-4 space-y-2">
          {entries.length === 0 && (
            <p className="text-slate-600 text-sm">
              No journal entries yet. Execute actions on the Actions screen to create entries.
            </p>
          )}
          {entries.map((entry) => {
            const isExit = ["sell", "trim"].includes(normalizeAction(entry.action_type));
            return (
              <Card key={entry.id} className="bg-slate-900 border-slate-800">
                <CardContent className="px-4 py-3">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3 flex-wrap">
                      {entry.ticker ? (
                        <a
                          href={`/stocks/${entry.ticker}`}
                          className="font-mono font-semibold text-indigo-400 hover:text-indigo-300"
                        >
                          {entry.ticker}
                        </a>
                      ) : (
                        <span className="font-medium text-slate-300">No ticker</span>
                      )}
                      {entry.skipped_month ? (
                        <Badge variant="outline" className="border-yellow-700 text-yellow-500 text-xs">
                          SKIPPED MONTH
                        </Badge>
                      ) : (
                        <span className={`text-sm font-semibold ${actionColor(entry.action_type)}`}>
                          {actionLabel(entry.action_type)}
                        </span>
                      )}
                      {entry.bucket && (
                        <span className="text-xs text-slate-600">{bucketLabel(entry.bucket)}</span>
                      )}
                      <span className="text-xs text-slate-600">{fmtDate(entry.action_date)}</span>
                    </div>
                    <button
                      onClick={() => (editId === entry.id ? setEditId(null) : startEdit(entry))}
                      className="text-xs text-slate-600 hover:text-slate-400 shrink-0"
                    >
                      {editId === entry.id ? "Cancel" : "Edit"}
                    </button>
                  </div>

                  {entry.thesis && (
                    <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">{entry.thesis}</p>
                  )}

                  <div className="flex items-center gap-4 mt-2 text-xs text-slate-600 flex-wrap">
                    {entry.suggested_price != null && (
                      <span>
                        Suggested:{" "}
                        <span className="font-mono text-slate-500">
                          {fmtNum(entry.suggested_price, 2)}
                        </span>
                      </span>
                    )}
                    {entry.fill_price != null && (
                      <span>
                        Fill:{" "}
                        <span className="font-mono text-slate-400">{fmtNum(entry.fill_price, 2)}</span>
                      </span>
                    )}
                    {entry.qty != null && (
                      <span>
                        Qty: <span className="font-mono text-slate-400">{entry.qty}</span>
                      </span>
                    )}
                  </div>

                  {entry.notes && (
                    <p className="text-xs text-slate-500 mt-1.5 italic">{entry.notes}</p>
                  )}
                  {entry.lesson && (
                    <p className="text-xs text-indigo-400 mt-1 italic">&ldquo;{entry.lesson}&rdquo;</p>
                  )}

                  {editId === entry.id && (
                    <div className="mt-3 space-y-2 border-t border-slate-800 pt-3">
                      <div className="flex items-center gap-3">
                        <label className="text-xs text-slate-500 w-20 shrink-0">Fill price</label>
                        <input
                          type="number"
                          value={editFill}
                          onChange={(event) => setEditFill(event.target.value)}
                          className="h-7 w-32 rounded bg-slate-800 border border-slate-700 text-slate-100 text-xs px-2 font-mono"
                        />
                      </div>
                      <div className="flex items-start gap-3">
                        <label className="text-xs text-slate-500 w-20 shrink-0 mt-1">Notes</label>
                        <textarea
                          value={editNotes}
                          onChange={(event) => setEditNotes(event.target.value)}
                          rows={2}
                          className="flex-1 rounded bg-slate-800 border border-slate-700 text-slate-100 text-xs px-2 py-1 resize-none"
                        />
                      </div>
                      {isExit && (
                        <div className="flex items-start gap-3">
                          <label className="text-xs text-indigo-400 w-20 shrink-0 mt-1">
                            Lesson
                          </label>
                          <textarea
                            value={editLesson}
                            onChange={(event) => setEditLesson(event.target.value)}
                            rows={2}
                            placeholder="Required for exits."
                            className="flex-1 rounded bg-slate-800 border border-indigo-800 text-slate-100 text-xs px-2 py-1 resize-none"
                          />
                        </div>
                      )}
                      {error && <p className="text-xs text-red-400">{error}</p>}
                      <div className="flex justify-end">
                        <button
                          onClick={() => handleSave(entry)}
                          className="text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1 rounded"
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
            <p className="text-slate-600 text-sm">No review data yet.</p>
          ) : (
            reviews.map((review) => (
              <Card key={review.month} className="bg-slate-900 border-slate-800">
                <CardHeader className="px-4 pt-4 pb-2">
                  <CardTitle className="text-sm text-slate-100">{review.month}</CardTitle>
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
                      <div key={label} className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-3">
                        <p className="text-xs text-slate-500">{label}</p>
                        <p className="text-sm font-mono text-slate-100 mt-1">{value}</p>
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

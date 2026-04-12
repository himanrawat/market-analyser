"use client";

import { useEffect, useState } from "react";
import { api, PortfolioResponse, Country } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  fmtNum,
  fmtPct,
  fmtINR,
  countryFlag,
} from "@/lib/format";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Plus, Trash2, AlertTriangle, Pencil } from "lucide-react";

const SECTOR_COLORS = [
  "#6366f1", "#8b5cf6", "#a855f7", "#ec4899", "#f43f5e",
  "#f97316", "#eab308", "#22c55e", "#14b8a6", "#06b6d4",
];

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({
    ticker: "",
    country: "IN" as Country,
    qty: "",
    avg_price: "",
    buy_date: new Date().toISOString().slice(0, 10),
  });

  function reload() {
    api
      .portfolio()
      .then((d) => {
        console.log(`[Portfolio] received holdings=${d.holdings.length} total_value=${d.summary.total_value}`);
        setData(d);
      })
      .catch((err) => console.error("[Portfolio] fetch error:", err))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    reload();
  }, []);

  function resetForm() {
    setForm({ ticker: "", country: "IN", qty: "", avg_price: "", buy_date: new Date().toISOString().slice(0, 10) });
    setEditingId(null);
  }

  function openAddDialog() {
    resetForm();
    setEditorOpen(true);
  }

  function openEditDialog(id: number) {
    const holding = data?.holdings.find((item) => item.id === id);
    if (!holding) return;
    setEditingId(id);
    setForm({
      ticker: holding.ticker,
      country: holding.country,
      qty: String(holding.qty),
      avg_price: String(holding.avg_price),
      buy_date: holding.buy_date.slice(0, 10),
    });
    setEditorOpen(true);
  }

  async function handleSave() {
    const payload = {
      qty: Number(form.qty),
      avg_price: Number(form.avg_price),
      buy_date: form.buy_date,
    };
    if (editingId != null) {
      await api.updateHolding(editingId, payload);
    } else {
      await api.addHolding({
        ticker: form.ticker.toUpperCase(),
        country: form.country,
        ...payload,
      });
    }
    setEditorOpen(false);
    resetForm();
    reload();
  }

  async function handleDelete(id: number) {
    await api.deleteHolding(id);
    reload();
  }

  if (loading) return <p className="text-slate-500 text-sm">Loading portfolio…</p>;

  if (!data) return <p className="text-slate-500 text-sm">Could not load portfolio.</p>;

  const { holdings, summary } = data;

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Portfolio</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {holdings.length} holdings
          </p>
        </div>
        <Button
          size="sm"
          className="h-8 text-xs bg-indigo-600 hover:bg-indigo-500 gap-1.5"
          onClick={openAddDialog}
        >
          <Plus className="h-3.5 w-3.5" /> Add holding
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="bg-slate-900 border-slate-800">
          <CardContent className="px-4 py-3">
            <p className="text-xs text-slate-500">Total Value</p>
            <p className="text-xl font-mono text-slate-100">{fmtINR(summary.total_value)}</p>
          </CardContent>
        </Card>
        <Card className="bg-slate-900 border-slate-800">
          <CardContent className="px-4 py-3">
            <p className="text-xs text-slate-500">Total P&L</p>
            <p className={`text-xl font-mono ${summary.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
              {fmtINR(summary.total_pnl)}
            </p>
            <p className={`text-xs ${summary.total_pnl_pct >= 0 ? "text-green-500" : "text-red-500"}`}>
              {fmtPct(summary.total_pnl_pct)}
            </p>
          </CardContent>
        </Card>
        <Card className="bg-slate-900 border-slate-800">
          <CardContent className="px-4 py-3">
            <p className="text-xs text-slate-500">🇮🇳 India</p>
            <p className="text-xl font-mono text-slate-100">{fmtINR(summary.india_value)}</p>
            <p className="text-xs text-slate-500">{fmtNum(summary.india_pct, 1)}%</p>
          </CardContent>
        </Card>
        <Card className="bg-slate-900 border-slate-800">
          <CardContent className="px-4 py-3">
            <p className="text-xs text-slate-500">🇺🇸 US</p>
            <p className="text-xl font-mono text-slate-100">${fmtNum(summary.us_value / 83, 0)}</p>
            <p className="text-xs text-slate-500">{fmtNum(summary.us_pct, 1)}%</p>
          </CardContent>
        </Card>
      </div>

      {/* Benchmarks */}
      {summary.benchmarks.length > 0 && (
        <div className="flex items-center gap-4 flex-wrap">
          <span className="text-xs text-slate-600">vs benchmarks:</span>
          {summary.benchmarks.map((b) => (
            <span key={b.name} className="text-xs text-slate-400">
              {b.name}{" "}
              <span className={b.return_pct != null && b.return_pct >= 0 ? "text-green-400" : "text-red-400"}>
                {b.return_pct != null ? fmtPct(b.return_pct) : "—"}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Sector pie */}
        <Card className="bg-slate-900 border-slate-800">
          <CardHeader className="px-4 pt-4 pb-2">
            <CardTitle className="text-xs text-slate-500 font-normal">Sector Allocation</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {(summary.sector_allocations ?? []).length === 0 ? (
              <p className="text-slate-600 text-sm">No data.</p>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie
                    data={summary.sector_allocations ?? []}
                    dataKey="pct"
                    nameKey="sector"
                    cx="50%"
                    cy="50%"
                    outerRadius={70}
                    innerRadius={30}
                  >
                    {(summary.sector_allocations ?? []).map((entry, i) => (
                      <Cell key={entry.sector} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
                    formatter={(v) => [`${Number(v).toFixed(1)}%`, "Allocation"]}
                  />
                  <Legend
                    iconSize={8}
                    formatter={(v) => <span className="text-xs text-slate-400">{v}</span>}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
            {(summary.sector_allocations ?? []).some((s) => s.pct > 25) && (
              <div className="flex items-center gap-1.5 mt-2 text-yellow-400 text-xs">
                <AlertTriangle className="h-3 w-3" />
                Sector concentration &gt; 25%
              </div>
            )}
          </CardContent>
        </Card>

        {/* Holdings table */}
        <div className="lg:col-span-2">
          <Card className="bg-slate-900 border-slate-800">
            <CardContent className="p-0">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-600">
                    <th className="text-left px-4 py-2.5 font-normal">Ticker</th>
                    <th className="text-right px-4 py-2.5 font-normal">Qty</th>
                    <th className="text-right px-4 py-2.5 font-normal">Avg</th>
                    <th className="text-right px-4 py-2.5 font-normal">LTP</th>
                    <th className="text-right px-4 py-2.5 font-normal">P&L%</th>
                    <th className="text-right px-4 py-2.5 font-normal">Days</th>
                    <th className="text-center px-4 py-2.5 font-normal">Tax</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {holdings.map((h) => (
                    <tr key={h.id} className="border-b border-slate-800/40 last:border-0 hover:bg-slate-800/30">
                      <td className="px-4 py-2.5">
                        <a href={`/stocks/${h.ticker}`} className="text-indigo-400 hover:text-indigo-300 font-mono font-medium">
                          {h.ticker}
                        </a>
                        <span className="ml-1 text-slate-600">{countryFlag(h.country)}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-300">{h.qty}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-400">{fmtNum(h.avg_price, 2)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-slate-300">
                        {h.current_price != null ? fmtNum(h.current_price, 2) : "—"}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono ${h.unrealized_pnl_pct != null && h.unrealized_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {h.unrealized_pnl_pct != null ? fmtPct(h.unrealized_pnl_pct, 1) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right text-slate-500">{h.days_held}</td>
                      <td className="px-4 py-2.5 text-center">
                        {h.ltcg_status && (
                          <span className={`text-xs font-medium ${h.ltcg_status === "LTCG" ? "text-green-500" : h.ltcg_status === "STCG" ? "text-yellow-500" : "text-orange-400"}`}>
                            {h.ltcg_status}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => openEditDialog(h.id)}
                            className="text-slate-700 hover:text-slate-300 transition-colors"
                            title="Edit holding"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleDelete(h.id)}
                            className="text-slate-700 hover:text-red-400 transition-colors"
                            title="Delete holding"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Add holding dialog */}
      <Dialog
        open={editorOpen}
        onOpenChange={(open) => {
          setEditorOpen(open);
          if (!open) resetForm();
        }}
      >
        <DialogContent className="bg-slate-900 border-slate-700 text-slate-100">
          <DialogHeader>
            <DialogTitle>{editingId != null ? "Edit Holding" : "Add Holding"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {(
              [
                { label: "Ticker", key: "ticker", type: "text", placeholder: "e.g. RELIANCE or AAPL" },
                { label: "Quantity", key: "qty", type: "number", placeholder: "e.g. 10" },
                { label: "Avg Buy Price", key: "avg_price", type: "number", placeholder: "e.g. 2500" },
                { label: "Buy Date", key: "buy_date", type: "date", placeholder: "" },
              ] as const
            ).map(({ label, key, type, placeholder }) => (
              <div key={key}>
                <label className="text-xs text-slate-500 block mb-1">{label}</label>
                <input
                  type={type}
                  value={form[key]}
                  onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                  placeholder={placeholder}
                  disabled={editingId != null && key === "ticker"}
                  className="w-full h-8 rounded-md bg-slate-800 border border-slate-700 text-slate-100 text-sm px-3"
                />
              </div>
            ))}
            <div>
              <label className="text-xs text-slate-500 block mb-1">Market</label>
              <select
                value={form.country}
                onChange={(e) => setForm((p) => ({ ...p, country: e.target.value as Country }))}
                disabled={editingId != null}
                className="w-full h-8 rounded-md bg-slate-800 border border-slate-700 text-slate-100 text-sm px-3"
              >
                <option value="IN">🇮🇳 India (NSE/BSE)</option>
                <option value="US">🇺🇸 US</option>
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="ghost" size="sm" className="text-slate-400" onClick={() => setEditorOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="bg-indigo-600 hover:bg-indigo-500"
              onClick={handleSave}
              disabled={!form.ticker || !form.qty || !form.avg_price}
            >
              {editingId != null ? "Save" : "Add"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* LTCG warning */}
      {holdings.some((h) => h.ltcg_status === "LTCG_WARN") && (
        <Card className="bg-yellow-900/20 border-yellow-800/40">
          <CardContent className="px-4 py-3 flex items-center gap-2 text-yellow-400 text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Some holdings are approaching 12 months — selling now would attract STCG instead of LTCG.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { api, SettingsResponse, Bucket } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { bucketLabel } from "@/lib/format";
import { Settings, Save, Play, Link2, RefreshCw } from "lucide-react";

const BUCKET_ORDER: Bucket[] = [
  "quality_value",
  "momentum",
  "quality_momentum",
  "dividend_growth",
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineMsg, setPipelineMsg] = useState("");

  // Kite Connect
  const [kiteConnected, setKiteConnected] = useState(false);
  const [kiteTokenDate, setKiteTokenDate] = useState<string | null>(null);
  const [kiteStale, setKiteStale] = useState(false);
  const [kiteApiKeySet, setKiteApiKeySet] = useState(false);
  const [kiteSyncing, setKiteSyncing] = useState(false);
  const [kiteSyncMsg, setKiteSyncMsg] = useState("");

  useEffect(() => {
    api
      .settings()
      .then((s) => {
        console.log("[Settings] received:", s);
        setSettings(s);
      })
      .catch((err) => console.error("[Settings] fetch error:", err))
      .finally(() => setLoading(false));

    // Check Kite connection status
    api.kiteStatus().then((s) => {
      setKiteConnected(s.connected);
      setKiteTokenDate(s.token_date);
      setKiteStale(s.stale);
      setKiteApiKeySet(s.api_key_set);
    }).catch(() => {});

    // Detect redirect back from Zerodha OAuth
    const params = new URLSearchParams(globalThis.location.search);
    const kiteParam = params.get("kite");
    const syncedParam = params.get("synced");
    const skippedParam = params.get("skipped");
    const syncParam = params.get("sync");
    if (kiteParam === "connected") {
      if (syncParam === "error") {
        setKiteSyncMsg("Kite connected, but holdings sync failed. Click Sync Holdings to retry.");
      } else if (syncedParam != null) {
        const syncedCount = Number(syncedParam);
        const skippedCount = Number(skippedParam ?? "0");
        const skippedText = skippedCount > 0 ? ` (${skippedCount} zero-quantity skipped)` : "";
        setKiteSyncMsg(
          `Kite connected and synced ${syncedCount} holding${syncedCount === 1 ? "" : "s"}${skippedText}.`,
        );
      } else {
        setKiteSyncMsg("Kite connected successfully! Click Sync to import your holdings.");
      }
      globalThis.history.replaceState({}, "", "/settings");
      api.kiteStatus().then((s) => {
        setKiteConnected(s.connected);
        setKiteTokenDate(s.token_date);
        setKiteStale(s.stale);
      }).catch(() => {});
    } else if (kiteParam === "error") {
      setKiteSyncMsg("Kite login failed. Check your API key/secret and try again.");
      globalThis.history.replaceState({}, "", "/settings");
    }
  }, []);

  async function handleSave() {
    if (!settings) return;
    setSaving(true);
    try {
      const updated = await api.saveSettings(settings);
      setSettings(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }

  async function handleKiteConnect() {
    try {
      const { login_url } = await api.kiteLogin();
      globalThis.open(login_url, "_blank");
    } catch {
      setKiteSyncMsg("Could not get Kite login URL. Is KITE_API_KEY set in .env?");
    }
  }

  async function handleKiteSync() {
    setKiteSyncing(true);
    setKiteSyncMsg("");
    try {
      const res = await api.kiteSync();
      setKiteSyncMsg(`Synced ${res.upserted} holding${res.upserted === 1 ? "" : "s"} from Kite.`);
      // Refresh holdings count
      const status = await api.kiteStatus();
      setKiteConnected(status.connected);
      setKiteTokenDate(status.token_date);
      setKiteStale(status.stale);
    } catch {
      setKiteSyncMsg("Sync failed. Your session may have expired — reconnect Kite.");
    } finally {
      setKiteSyncing(false);
    }
  }

  async function handleRunPipeline() {
    setPipelineRunning(true);
    setPipelineMsg("Pipeline started…");
    try {
      const res = await api.runPipeline();
      setPipelineMsg(res.message);
    } catch {
      setPipelineMsg("Failed to start pipeline. Is the API running?");
    } finally {
      setPipelineRunning(false);
    }
  }

  function update<K extends keyof SettingsResponse>(key: K, value: SettingsResponse[K]) {
    setSettings((prev) => prev ? { ...prev, [key]: value } : prev);
  }

  if (loading) return <p className="text-slate-500 text-sm">Loading settings…</p>;
  if (!settings) return <p className="text-slate-500 text-sm">Could not load settings.</p>;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold text-slate-100 flex items-center gap-2">
          <Settings className="h-5 w-5 text-slate-400" /> Settings
        </h1>
        <Button
          size="sm"
          className="h-8 text-xs bg-indigo-600 hover:bg-indigo-500 gap-1.5"
          onClick={handleSave}
          disabled={saving}
        >
          <Save className="h-3.5 w-3.5" />
          {saved ? "Saved!" : saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {/* Rebalance settings */}
      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-slate-100">Rebalance</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-4">
          <div className="flex items-center gap-4">
            <label className="text-xs text-slate-400 w-36 shrink-0">Rebalance day</label>
            <input
              type="number"
              min={1}
              max={28}
              value={settings.rebalance_day}
              onChange={(e) => update("rebalance_day", Number(e.target.value))}
              className="h-8 w-20 rounded-md bg-slate-800 border border-slate-700 text-slate-100 text-sm px-3 font-mono"
            />
            <span className="text-xs text-slate-600">of each month (shifts to next trading day if holiday)</span>
          </div>

          <div className="flex items-center gap-4">
            <label className="text-xs text-slate-400 w-36 shrink-0">Universe — India</label>
            <Select value={settings.universe_india} onValueChange={(v) => update("universe_india", v ?? settings.universe_india)}>
              <SelectTrigger className="w-40 h-8 text-xs bg-slate-800 border-slate-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-900 border-slate-700">
                <SelectItem value="nifty50" className="text-xs">Nifty 50</SelectItem>
                <SelectItem value="nifty500" className="text-xs">Nifty 500</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-4">
            <label className="text-xs text-slate-400 w-36 shrink-0">Universe — US</label>
            <Select value={settings.universe_us} onValueChange={(v) => update("universe_us", v ?? settings.universe_us)}>
              <SelectTrigger className="w-40 h-8 text-xs bg-slate-800 border-slate-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-900 border-slate-700">
                <SelectItem value="sp100" className="text-xs">S&P 100</SelectItem>
                <SelectItem value="sp500" className="text-xs">S&P 500</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Picks & allocation */}
      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-slate-100">Picks & Allocation</CardTitle>
          <p className="text-xs text-slate-600 mt-0.5">
            Advanced — set once and forget. Changing monthly defeats the purpose of a rules-based system.
          </p>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-4">
          <div className="flex items-center gap-4">
            <label className="text-xs text-slate-400 w-36 shrink-0">Picks per bucket</label>
            <Select value={String(settings.picks_per_bucket)} onValueChange={(v) => update("picks_per_bucket", Number(v))}>
              <SelectTrigger className="w-28 h-8 text-xs bg-slate-800 border-slate-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-900 border-slate-700">
                {[5, 10, 15, 20].map((n) => (
                  <SelectItem key={n} value={String(n)} className="text-xs">Top {n}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-3">
            <p className="text-xs text-slate-500">Default bucket allocations (% of monthly capital)</p>
            {BUCKET_ORDER.map((b) => {
              const pct = settings.bucket_allocations[b] ?? 0;
              return (
                <div key={b} className="flex items-center gap-4">
                  <span className="text-xs text-slate-400 w-40 shrink-0">{bucketLabel(b)}</span>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={[pct]}
                    onValueChange={(vals) => {
                      const v = Array.isArray(vals) ? vals[0] : vals;
                      update("bucket_allocations", { ...settings.bucket_allocations, [b]: v ?? pct });
                    }}
                    className="flex-1"
                  />
                  <span className="text-xs font-mono text-slate-300 w-8 text-right">{pct}%</span>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Notifications */}
      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-slate-100">Notifications</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          {(
            [
              { key: "notify_telegram" as const, label: "Telegram digest (rebalance day + RED shocks)" },
              { key: "notify_email" as const, label: "Email digest" },
              { key: "shock_detection" as const, label: "Market shock detection (Stream 2)" },
              { key: "stock_news" as const, label: "Stock-specific news feed (Stream 1)" },
            ] as const
          ).map(({ key, label }) => (
            <label key={key} className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={settings[key]}
                onChange={(e) => update(key, e.target.checked)}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 accent-indigo-500"
              />
              <span className="text-sm text-slate-300">{label}</span>
            </label>
          ))}
        </CardContent>
      </Card>

      {/* Kite Connect */}
      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-slate-100">Kite Connect (Zerodha)</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          {kiteApiKeySet ? (
            <>
              <KiteStatusLine connected={kiteConnected} stale={kiteStale} tokenDate={kiteTokenDate} />
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs border-slate-700 text-slate-300 gap-1.5"
                  onClick={handleKiteConnect}
                >
                  <Link2 className="h-3.5 w-3.5" />
                  {kiteConnected && kiteStale === false ? "Reconnect" : "Connect Kite"}
                </Button>
                {kiteConnected && !kiteStale && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs border-slate-700 text-slate-300 gap-1.5"
                    onClick={handleKiteSync}
                    disabled={kiteSyncing}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${kiteSyncing ? "animate-spin" : ""}`} />
                    {kiteSyncing ? "Syncing…" : "Sync Holdings"}
                  </Button>
                )}
              </div>
              {kiteSyncMsg && (
                <p className="text-xs text-slate-500">{kiteSyncMsg}</p>
              )}
              <p className="text-xs text-slate-600">
                We auto-sync on connect, and you can use Sync Holdings later to refresh. Token expires daily at 6 am,
                so reconnect each morning before syncing again.
              </p>
            </>
          ) : (
            <p className="text-xs text-slate-500">
              Set <code className="text-slate-400">KITE_API_KEY</code> and{" "}
              <code className="text-slate-400">KITE_API_SECRET</code> in your{" "}
              <code className="text-slate-400">.env</code> file, then restart the API.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Pipeline trigger */}
      <Card className="bg-slate-900 border-slate-800">
        <CardHeader className="px-4 pt-4 pb-3">
          <CardTitle className="text-sm font-semibold text-slate-100">Pipeline</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          <p className="text-xs text-slate-500">
            The pipeline normally runs automatically on the 6th via cron. Use this to trigger it manually.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs border-slate-700 text-slate-300 gap-1.5"
            onClick={handleRunPipeline}
            disabled={pipelineRunning}
          >
            <Play className="h-3.5 w-3.5" />
            Run pipeline now
          </Button>
          {pipelineMsg && (
            <p className="text-xs text-slate-500">{pipelineMsg}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function KiteStatusLine({
  connected,
  stale,
  tokenDate,
}: Readonly<{
  connected: boolean;
  stale: boolean;
  tokenDate: string | null;
}>) {
  const isActive = connected && stale === false;
  let label: string;
  if (isActive) {
    label = `Connected · token valid for today (${tokenDate})`;
  } else if (connected) {
    label = `Token expired (last: ${tokenDate}) — reconnect`;
  } else {
    label = "Not connected";
  }
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className={`inline-block w-2 h-2 rounded-full ${isActive ? "bg-green-500" : "bg-slate-600"}`} />
      <span className="text-slate-400">{label}</span>
    </div>
  );
}

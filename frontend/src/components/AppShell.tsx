"use client";

import { useEffect, useState } from "react";
import { MacroHeader } from "./MacroHeader";
import { ShockBanner } from "./ShockBanner";
import { api, DashboardResponse } from "@/lib/api";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);

  useEffect(() => {
    api.dashboard().then(setDashboard).catch(() => {});
    // Refresh every 5 minutes
    const id = setInterval(() => {
      api.dashboard().then(setDashboard).catch(() => {});
    }, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      {dashboard?.shock && <ShockBanner shock={dashboard.shock} />}
      <MacroHeader data={dashboard} />
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </>
  );
}

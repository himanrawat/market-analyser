import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Market Analyser",
  description: "Personal stock picker & monthly rebalance tool",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className="h-full bg-slate-950 text-slate-100">
        <div className="flex h-full">
          <Sidebar />
          <div className="flex flex-col flex-1 min-w-0 h-full overflow-hidden">
            <AppShell>{children}</AppShell>
          </div>
        </div>
      </body>
    </html>
  );
}

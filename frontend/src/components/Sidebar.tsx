"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  List,
  Zap,
  BarChart2,
  BookOpen,
  Newspaper,
  Settings,
  TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/ranked", label: "Ranked Lists", icon: List },
  { href: "/actions", label: "Actions", icon: Zap },
  { href: "/portfolio", label: "Portfolio", icon: TrendingUp },
  { href: "/journal", label: "Journal", icon: BookOpen },
  { href: "/news", label: "News", icon: Newspaper },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const path = usePathname();

  return (
    <aside className="w-56 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col h-full">
      {/* Logo */}
      <div className="h-14 flex items-center gap-2 px-4 border-b border-slate-800">
        <BarChart2 className="h-5 w-5 text-indigo-400" />
        <span className="font-semibold text-slate-100 text-sm">Market Analyser</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-indigo-500/20 text-indigo-300 font-medium"
                  : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Version */}
      <div className="px-4 py-3 border-t border-slate-800 text-xs text-slate-600">
        v1.1 · Personal tool
      </div>
    </aside>
  );
}

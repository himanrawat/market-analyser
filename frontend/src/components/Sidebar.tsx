"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import {
  LayoutDashboard,
  List,
  Zap,
  BarChart2,
  BookOpen,
  Newspaper,
  Settings,
  TrendingUp,
  X,
  Menu,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "./theme-toggle";

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
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [path]);

  // Close on escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    if (mobileOpen) {
      document.addEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="h-14 flex items-center gap-2.5 px-4 border-b border-border">
        <div className="h-8 w-8 rounded-xl bg-primary flex items-center justify-center">
          <BarChart2 className="h-4 w-4 text-primary-foreground" />
        </div>
        <span className="font-semibold text-foreground text-sm tracking-tight">
          Market Analyser
        </span>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto scrollbar-thin">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-all duration-200 cursor-pointer",
                active
                  ? "bg-primary/15 text-primary font-medium"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground hover:translate-x-0.5"
              )}
            >
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-colors duration-200",
                  active ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
                )}
              />
              {label}
              {active && (
                <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary animate-pulse-ring" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-3 border-t border-border flex items-center justify-between">
        <span className="text-xs text-muted-foreground">v1.1</span>
        <ThemeToggle />
      </div>
    </>
  );

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-3 left-3 z-50 md:hidden h-10 w-10 rounded-xl bg-card border border-border flex items-center justify-center cursor-pointer hover:bg-accent transition-colors duration-200"
        aria-label="Open menu"
      >
        <Menu className="h-5 w-5 text-foreground" />
      </button>

      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-56 shrink-0 bg-card border-r border-border flex-col h-full">
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-50 md:hidden"
          onClick={() => setMobileOpen(false)}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in-up" style={{ animationDuration: "150ms" }} />

          {/* Drawer */}
          <aside
            className="absolute left-0 top-0 bottom-0 w-64 bg-card border-r border-border flex flex-col animate-slide-in-left"
            style={{
              animation: "slideInLeft 0.25s ease-out both",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close button */}
            <button
              onClick={() => setMobileOpen(false)}
              className="absolute top-3 right-3 h-8 w-8 rounded-lg bg-muted flex items-center justify-center hover:bg-accent transition-colors cursor-pointer"
              aria-label="Close menu"
            >
              <X className="h-4 w-4 text-foreground" />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      <style jsx>{`
        @keyframes slideInLeft {
          from { transform: translateX(-100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </>
  );
}

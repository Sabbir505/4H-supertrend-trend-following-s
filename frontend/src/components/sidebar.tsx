"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
  Activity,
  Zap,
  FlaskConical,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebarState } from "@/components/sidebar-state";

const navSections = [
  {
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/signals", label: "Signals", icon: Activity },
      { href: "/backtest", label: "Backtest", icon: FlaskConical },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { collapsed, toggle } = useSidebarState();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Hydration guard for the theme label: `theme` from next-themes is only
    // known on the client, so mount must flip state after hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  const toggleCollapse = toggle;

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-screen flex flex-col z-50 transition-all duration-300",
        "backdrop-blur-2xl",
        "border-r border-sidebar-border",
        "bg-sidebar/80",
        "shadow-[0_8px_32px_rgba(15,23,42,0.16),inset_1px_0_0_rgba(255,255,255,0.04)]",
        collapsed ? "w-[72px]" : "w-[260px]"
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          "flex items-center border-b border-sidebar-border shrink-0 relative",
          collapsed ? "px-3 py-5 justify-center" : "px-5 py-5 gap-3"
        )}
      >
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-400 to-blue-500 flex items-center justify-center shrink-0 shadow-[0_0_20px_rgba(6,182,212,0.4)]">
          <Zap className="w-4.5 h-4.5 text-primary-foreground" strokeWidth={2.5} />
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <span className="text-[15px] font-bold text-foreground block leading-tight tracking-tight">
              TradeEdge
            </span>
            <span className="text-[11px] text-muted-foreground block leading-tight mt-0.5">
              Signal Terminal
            </span>
          </div>
        )}
        <button
          onClick={toggleCollapse}
          className={cn(
            "flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-sidebar-accent transition-all shrink-0",
            collapsed
              ? "absolute -right-3 top-6 w-6 h-6 bg-card border border-border rounded-full shadow-md"
              : "w-7 h-7"
          )}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5" />
          ) : (
            <ChevronLeft className="w-3.5 h-3.5" />
          )}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3">
        {navSections.map((section) => (
          <div key={section.label} className="mb-4">
            {!collapsed && (
              <p className="text-[10px] uppercase tracking-[0.1em] font-semibold text-muted-foreground/70 px-3 mb-2">
                {section.label}
              </p>
            )}
            <div className="space-y-1">
              {section.items.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-xl text-[13px] font-medium transition-all relative overflow-hidden",
                      isActive
                        ? "bg-gradient-to-r from-cyan-500/15 to-blue-500/10 text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_4px_12px_rgba(6,182,212,0.1)]"
                        : "text-sidebar-foreground hover:text-foreground hover:bg-sidebar-accent",
                      collapsed && "justify-center px-2"
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    {isActive && (
                      <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-cyan-400 rounded-r-full shadow-[0_0_8px_rgba(6,182,212,0.6)]" />
                    )}
                    <Icon
                      className={cn(
                        "w-[18px] h-[18px] shrink-0 transition-colors",
                        isActive ? "text-cyan-400" : "text-muted-foreground"
                      )}
                    />
                    {!collapsed && item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Bottom Section */}
      <div className="shrink-0 border-t border-sidebar-border">
        {/* Theme Toggle */}
        <div className={cn("px-3 pt-3 pb-1.5", collapsed && "flex justify-center")}>
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className={cn(
              "flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-[13px] font-medium text-sidebar-foreground hover:text-foreground hover:bg-sidebar-accent transition-all w-full",
              collapsed && "justify-center px-2 w-auto"
            )}
            title={collapsed ? "Toggle theme" : undefined}
          >
            <Sun className="w-[18px] h-[18px] shrink-0 hidden dark:block" />
            <Moon className="w-[18px] h-[18px] shrink-0 dark:hidden" />
            {!collapsed && mounted && (
              <span>{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
            )}
            {!collapsed && !mounted && <span>Toggle theme</span>}
          </button>
        </div>

        {/* Scanner Status */}
        <div className={cn("px-3 pb-3 pt-1.5", collapsed && "flex justify-center")}>
          <div
            className={cn(
              "flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-emerald-500/[0.08] border border-emerald-500/[0.15]",
              collapsed && "px-2"
            )}
          >
            <div className="relative w-2 h-2 shrink-0">
              <div className="absolute inset-0 rounded-full bg-emerald-400 animate-ping opacity-75" />
              <div className="relative w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <span className="text-[13px] font-medium text-foreground block leading-tight">
                  Scanner Active
                </span>
                <span className="text-[11px] text-muted-foreground block leading-tight mt-0.5">
                  ST 10/3.5 · 4H Trend-Ride
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
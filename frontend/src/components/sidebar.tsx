"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  Activity,
  Clock,
  BarChart3,
  FlaskConical,
  Newspaper,
  TrendingUp,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navSections = [
  {
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/live-trades", label: "Live Trades", icon: Activity },
    ],
  },
  {
    label: "Analysis",
    items: [
      { href: "/trade-history", label: "Trade History", icon: Clock },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/backtest", label: "Backtest", icon: FlaskConical },
      { href: "/market-intel", label: "Market Intel", icon: Newspaper },
    ],
  },
];

export function Sidebar({
  onCollapseChange,
}: { onCollapseChange?: (collapsed: boolean) => void } = {}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const { theme, setTheme } = useTheme();

  const toggleCollapse = () => {
    const newState = !collapsed;
    setCollapsed(newState);
    onCollapseChange?.(newState);
  };

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-screen bg-sidebar border-r border-sidebar-border flex flex-col z-50 transition-all duration-300",
        collapsed ? "w-[60px]" : "w-[250px]"
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          "flex items-center border-b border-sidebar-border shrink-0",
          collapsed ? "px-2 py-4 justify-center" : "px-5 py-4 gap-3"
        )}
      >
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
          <TrendingUp className="w-4 h-4 text-primary-foreground" />
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <span className="text-sm font-semibold text-foreground block leading-tight">
              TradeEdge
            </span>
            <span className="text-[11px] text-muted-foreground block leading-tight">
              Signal Dashboard
            </span>
          </div>
        )}
        <button
          onClick={toggleCollapse}
          className={cn(
            "flex items-center justify-center w-6 h-6 rounded-md text-muted-foreground hover:text-foreground hover:bg-sidebar-accent transition-colors shrink-0",
            collapsed &&
              "absolute -right-3 top-5 w-6 h-6 bg-card border border-border rounded-full shadow-sm"
          )}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="w-3 h-3" />
          ) : (
            <ChevronLeft className="w-3 h-3" />
          )}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {navSections.map((section) => (
          <div key={section.label} className="mb-4">
            {!collapsed && (
              <p className="text-[10px] uppercase tracking-wider font-medium text-muted-foreground px-3 mb-1.5">
                {section.label}
              </p>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-colors",
                      isActive
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-sidebar-accent",
                      collapsed && "justify-center px-2"
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon
                      className={cn(
                        "w-[18px] h-[18px] shrink-0",
                        isActive ? "text-primary" : "text-muted-foreground"
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
        <div
          className={cn(
            "px-2 pt-3 pb-1",
            collapsed && "flex justify-center"
          )}
        >
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className={cn(
              "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] font-medium text-muted-foreground hover:text-foreground hover:bg-sidebar-accent transition-colors w-full",
              collapsed && "justify-center px-2 w-auto"
            )}
            title={collapsed ? "Toggle theme" : undefined}
          >
            <Sun className="w-[18px] h-[18px] shrink-0 hidden dark:block" />
            <Moon className="w-[18px] h-[18px] shrink-0 dark:hidden" />
            {!collapsed && (
              <span>{theme === "dark" ? "Light Mode" : "Dark Mode"}</span>
            )}
          </button>
        </div>

        {/* Bot Status */}
        <div
          className={cn(
            "px-2 pb-3 pt-1",
            collapsed && "flex justify-center"
          )}
        >
          <div
            className={cn(
              "flex items-center gap-2.5 px-3 py-2",
              collapsed && "px-0"
            )}
          >
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            {!collapsed && (
              <div>
                <span className="text-[13px] font-medium text-foreground">
                  Bot Active
                </span>
                <span className="text-[11px] text-muted-foreground block">
                  24/7 Crypto
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}

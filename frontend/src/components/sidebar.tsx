"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LayoutDashboard,
  Activity,
  Clock,
  BarChart3,
  FlaskConical,
  Settings,
  TrendingUp,
  Moon,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/live-trades", label: "Live Trades", icon: Activity },
  { href: "/trade-history", label: "Trade History", icon: Clock },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
];

export function Sidebar({ onCollapseChange }: { onCollapseChange?: (collapsed: boolean) => void } = {}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(true);

  const toggleCollapse = () => {
    const newState = !collapsed;
    setCollapsed(newState);
    onCollapseChange?.(newState);
  };

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 h-screen bg-[#0b0f19] border-r border-[#1e293b] flex flex-col z-50 transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Logo + Toggle */}
      <div className={cn("flex items-center border-b border-[#1e293b]", collapsed ? "px-2 py-5 justify-center" : "px-6 py-5 gap-3")}>
        <div className="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center flex-shrink-0">
          <TrendingUp className="w-5 h-5 text-[#0b0f19]" />
        </div>
        {!collapsed && (
          <div className="flex-1 min-w-0">
            <span className="text-lg font-bold text-white tracking-tight block leading-tight">TradeEdge</span>
            <span className="text-xs text-slate-500 block leading-tight mt-0.5">Signal Dashboard</span>
          </div>
        )}
        <button
          onClick={toggleCollapse}
          className={cn(
            "flex items-center justify-center w-6 h-6 rounded-md text-slate-400 hover:text-white hover:bg-[#1e293b]/50 transition-colors flex-shrink-0",
            collapsed && "absolute -right-3 top-6 w-6 h-6 bg-[#1e293b] border border-[#1e293b] rounded-full"
          )}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronLeft className="w-3 h-3" />}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors relative",
                isActive
                  ? "bg-[#1e3a5f] text-white"
                  : "text-slate-400 hover:text-white hover:bg-[#1e293b]/50",
                collapsed && "justify-center px-0"
              )}
              title={collapsed ? item.label : undefined}
            >
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 bg-[#3b82f6] rounded-r" />
              )}
              <Icon className={cn("w-5 h-5 flex-shrink-0", isActive ? "text-white" : "text-slate-400")} />
              {!collapsed && item.label}
            </Link>
          );
        })}
      </nav>

      {/* Market Status + Theme */}
      <div className="px-3 py-4 border-t border-[#1e293b] space-y-3">
        {!collapsed && (
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3">Market Status</p>
        )}
        <div className={cn("px-3", collapsed && "px-0 flex justify-center")}>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse flex-shrink-0" />
            {!collapsed && (
              <>
                <span className="text-sm text-white font-medium">Market Open</span>
              </>
            )}
          </div>
          {!collapsed && <p className="text-xs text-emerald-400 mt-0.5">All Systems Operational</p>}
        </div>
        <button
          onClick={() => alert("Theme toggle coming soon!")}
          className={cn(
            "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-[#1e293b]/50 transition-colors w-full",
            collapsed && "justify-center px-0"
          )}
          title={collapsed ? "Theme" : undefined}
        >
          <Moon className="w-5 h-5 flex-shrink-0" />
          {!collapsed && "Theme"}
        </button>
      </div>

      {/* User Profile */}
      <div className="px-3 py-4 border-t border-[#1e293b]">
        <div className={cn("flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-[#1e293b]/50 transition-colors cursor-pointer", collapsed && "justify-center px-0")}>
          <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
            <span className="text-sm font-bold text-[#0b0f19]">TR</span>
          </div>
          {!collapsed && (
            <>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-white truncate">Trader</p>
                <p className="text-xs text-slate-500">Pro Plan</p>
              </div>
              <ChevronDown className="w-4 h-4 text-slate-500 flex-shrink-0" />
            </>
          )}
        </div>
      </div>
    </aside>
  );
}

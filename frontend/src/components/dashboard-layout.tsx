"use client";

import { ReactNode } from "react";
import { Sidebar } from "@/components/sidebar";
import { useSidebarState } from "@/components/sidebar-state";
import { cn } from "@/lib/utils";

export function DashboardLayout({ children }: { children: ReactNode }) {
  const { collapsed } = useSidebarState();

  return (
    <div className="relative min-h-screen text-foreground">
      <Sidebar />
      <main
        className={cn(
          "flex-1 min-h-screen transition-all duration-300 p-6 sm:p-8",
          collapsed ? "ml-[72px]" : "ml-[260px]"
        )}
      >
        {children}
      </main>
    </div>
  );
}
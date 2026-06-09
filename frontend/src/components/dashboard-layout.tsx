"use client";

import { ReactNode, useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { cn } from "@/lib/utils";

export function DashboardLayout({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);

  return (
    <div className="flex min-h-screen">
      <Sidebar onCollapseChange={setSidebarCollapsed} />
      <main className={cn(
        "flex-1 p-6 bg-[#0b0f19] min-h-screen transition-all duration-300",
        sidebarCollapsed ? "ml-16" : "ml-64"
      )}>
        {children}
      </main>
    </div>
  );
}

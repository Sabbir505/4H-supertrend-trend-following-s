"use client";

import { ReactNode, useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { cn } from "@/lib/utils";

export function DashboardLayout({ children }: { children: ReactNode }) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar onCollapseChange={setSidebarCollapsed} />
      <main
        className={cn(
          "flex-1 min-h-screen transition-all duration-300 p-6",
          sidebarCollapsed ? "ml-[60px]" : "ml-[250px]"
        )}
      >
        {children}
      </main>
    </div>
  );
}

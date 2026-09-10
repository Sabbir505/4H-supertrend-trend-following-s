"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const STORAGE_KEY = "te_sidebar_collapsed";

interface SidebarState {
  collapsed: boolean;
  toggle: () => void;
}

const SidebarStateContext = createContext<SidebarState>({
  collapsed: false,
  toggle: () => {},
});

/**
 * Holds the sidebar collapse state above the routed pages so it survives
 * navigation (each page remounts DashboardLayout/Sidebar). The choice is
 * persisted to localStorage; hydration-safe — the first (server + first
 * client) render is expanded, then the stored value is restored.
 */
export function SidebarStateProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(STORAGE_KEY) === "1") {
        // Hydration guard: localStorage only exists on the client, so the
        // stored choice can only be restored after mount.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCollapsed(true);
      }
    } catch {
      // storage unavailable — stay expanded
    }
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  };

  return (
    <SidebarStateContext.Provider value={{ collapsed, toggle }}>
      {children}
    </SidebarStateContext.Provider>
  );
}

export function useSidebarState() {
  return useContext(SidebarStateContext);
}

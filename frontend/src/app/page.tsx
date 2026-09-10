"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { TrendingUp } from "lucide-react";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    router.push("/dashboard");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="glass rounded-2xl p-8 text-center animate-fade-in-up">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-400 to-blue-500 flex items-center justify-center mx-auto mb-5 shadow-[0_0_24px_rgba(6,182,212,0.4)]">
          <TrendingUp className="w-6 h-6 text-slate-950" strokeWidth={2.5} />
        </div>
        <div className="relative mb-4 mx-auto w-6 h-6">
          <div className="absolute inset-0 rounded-full border-2 border-white/10" />
          <div className="absolute inset-0 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin" />
        </div>
        <p className="text-sm font-medium text-foreground">TradeEdge</p>
        <p className="text-xs text-muted-foreground mt-1">Loading signal terminal…</p>
      </div>
    </div>
  );
}
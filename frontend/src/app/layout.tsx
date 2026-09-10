import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { SidebarStateProvider } from "@/components/sidebar-state";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TradeEdge — Supertrend Signal Terminal",
  description: "Professional crypto trading signal dashboard powered by Supertrend trend-ride (4H) and EMA200 trend filter",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen antialiased">
        {/* Animated mesh gradient background */}
        <div className="mesh-bg" aria-hidden="true" />
        <ThemeProvider>
          <SidebarStateProvider>{children}</SidebarStateProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

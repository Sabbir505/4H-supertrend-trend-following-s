"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, RefreshCw, Info } from "lucide-react";
import { getOpenSignals, getAnalyticsSummary, Signal, AnalyticsSummary } from "@/lib/api";
import { formatPrice } from "@/lib/utils";

interface TradeDisplay {
  id: string;
  symbol: string;
  direction: string;
  strength: string;
  entryPrice: number;
  currentPrice: number | null;
  slPrice: number;
  tp1Price: number;
  tp2Price: number;
  tp3Price: number;
  tp4Price: number;
  rr1: number;
  rr2: number;
  rr3: number;
  rrMax: number;
  qualityScore: number;
  timeAgo: string;
  firedAt: string;
  iconUrl: string;
  pnl: number | null;
  pnlPercent: number | null;
  status: string;
}

// CoinGecko numeric ID mapping for icon URLs
const coinGeckoIds: Record<string, { id: number; image: string }> = {
  BTCUSDT: { id: 1, image: "bitcoin" },
  ETHUSDT: { id: 279, image: "ethereum" },
  SOLUSDT: { id: 4124, image: "solana" },
  BNBUSDT: { id: 825, image: "bnb-icon2_2x" },
  XRPUSDT: { id: 44, image: "xrp-symbol-white-128" },
  ADAUSDT: { id: 975, image: "cardano" },
  DOTUSDT: { id: 12171, image: "polkadot" },
  AVAXUSDT: { id: 12559, image: "avalanche" },
  MATICUSDT: { id: 4713, image: "matic-network" },
  LINKUSDT: { id: 877, image: "chainlink" },
  LTCUSDT: { id: 2, image: "litecoin" },
  DOGEUSDT: { id: 5, image: "dogecoin" },
  SHIBUSDT: { id: 11939, image: "shiba" },
  UNIUSDT: { id: 12504, image: "uniswap" },
  ATOMUSDT: { id: 1481, image: "cosmos" },
  ALGOUSDT: { id: 4380, image: "algorand" },
  XLMUSDT: { id: 100, image: "stellar" },
  VETUSDT: { id: 1167, image: "vechain" },
  FILUSDT: { id: 12817, image: "filecoin" },
  TRXUSDT: { id: 1094, image: "tron" },
  ETCUSDT: { id: 1321, image: "ethereum-classic" },
  BCHUSDT: { id: 1839, image: "bitcoin-cash" },
  XMRUSDT: { id: 69, image: "monero" },
  XTZUSDT: { id: 667, image: "tezos" },
  ICPUSDT: { id: 14495, image: "internet-computer" },
  NEARUSDT: { id: 10365, image: "near" },
  ARBUSDT: { id: 16547, image: "arbitrum" },
  OPUSDT: { id: 25244, image: "optimism" },
  APTUSDT: { id: 26455, image: "aptos" },
  SUIUSDT: { id: 26375, image: "sui" },
  SEIUSDT: { id: 28206, image: "sei" },
  TIAUSDT: { id: 31700, image: "celestia" },
  INJUSDT: { id: 12895, image: "injective-protocol" },
  RNDRUSDT: { id: 11696, image: "render-token" },
  FETUSDT: { id: 3689, image: "fetch-ai" },
  AGIXUSDT: { id: 21324, image: "singularitynet" },
  OCEANUSDT: { id: 4630, image: "ocean-protocol" },
  GRTUSDT: { id: 13397, image: "the-graph" },
  SANDUSDT: { id: 9951, image: "the-sandbox" },
  MANAUSDT: { id: 13775, image: "decentraland" },
  AXSUSDT: { id: 13029, image: "axie-infinity" },
  ENJUSDT: { id: 1376, image: "enjin-coin" },
  CHZUSDT: { id: 1437, image: "chiliz" },
  FLOWUSDT: { id: 13401, image: "flow" },
  IMXUSDT: { id: 17686, image: "immutable-x" },
  CFXUSDT: { id: 5447, image: "conflux-token" },
  STXUSDT: { id: 4847, image: "blockstack" },
  ORDIUSDT: { id: 30912, image: "ordinals" },
  PEPEUSDT: { id: 29850, image: "pepe" },
  FLOKIUSDT: { id: 18740, image: "floki" },
  BONKUSDT: { id: 28615, image: "bonk" },
  WIFUSDT: { id: 33520, image: "dogwifcoin" },
  BOMEUSDT: { id: 36065, image: "book-of-meme" },
  WLDUSDT: { id: 27603, image: "worldcoin" },
  ARKUSDT: { id: 12912, image: "ark" },
  BEAMUSDT: { id: 14522, image: "beam" },
  PYTHUSDT: { id: 31974, image: "pyth-network" },
  JUPUSDT: { id: 33403, image: "jupiter-exchange-solana" },
  JTOUSDT: { id: 28984, image: "jito" },
  STRKUSDT: { id: 25000, image: "starknet" },
  ZKUSDT: { id: 30096, image: "zksync" },
  BLASTUSDT: { id: 34558, image: "blast" },
  MANTAUSDT: { id: 28104, image: "manta-network" },
  DYMUSDT: { id: 31016, image: "dymension" },
  TONUSDT: { id: 11419, image: "toncoin" },
  NOTUSDT: { id: 33428, image: "notcoin" },
  HMSTRUSDT: { id: 34556, image: "hamster-kombat" },
  DOGSUSDT: { id: 36776, image: "dogs" },
  CATIUSDT: { id: 36775, image: "catizen" },
  MAJORUSDT: { id: 36774, image: "major" },
  XAIUSDT: { id: 34557, image: "xai-blockchain" },
  APEUSDT: { id: 24478, image: "apecoin" },
  GMTUSDT: { id: 23542, image: "stepn" },
  COTIUSDT: { id: 3992, image: "coti" },
  ROSEUSDT: { id: 12713, image: "oasis-network" },
  KAVAUSDT: { id: 4846, image: "kava" },
  ZILUSDT: { id: 2469, image: "zilliqa" },
  ONEUSDT: { id: 3945, image: "harmony" },
  EGLDUSDT: { id: 11920, image: "elrond" },
  HBARUSDT: { id: 3688, image: "hedera-hashgraph" },
  QNTUSDT: { id: 3377, image: "quant-network" },
  THETAUSDT: { id: 1231, image: "theta-token" },
  IOTAUSDT: { id: 692, image: "iota" },
  KSMUSDT: { id: 15585, image: "kusama" },
  WAVESUSDT: { id: 12731, image: "waves" },
  DASHUSDT: { id: 131, image: "dash" },
  NEOUSDT: { id: 1378, image: "neo" },
  EOSUSDT: { id: 1765, image: "eos" },
  ICXUSDT: { id: 2090, image: "icon" },
  ONTUSDT: { id: 2097, image: "ontology" },
  ZRXUSDT: { id: 1371, image: "0x" },
  BATUSDT: { id: 1600, image: "basic-attention-token" },
  COMPUSDT: { id: 11414, image: "compound-governance-token" },
  AAVEUSDT: { id: 12604, image: "aave" },
  MKRUSDT: { id: 1368, image: "maker" },
  YFIUSDT: { id: 12718, image: "yearn-finance" },
  SNXUSDT: { id: 17040, image: "synthetix-network-token" },
  UMAUSDT: { id: 12440, image: "uma" },
  BALUSDT: { id: 11675, image: "balancer" },
  LRCUSDT: { id: 7667, image: "loopring" },
  RENUSDT: { id: 2539, image: "ren" },
  KNCUSDT: { id: 4049, image: "kyber-network-crystal" },
  BNTUSDT: { id: 1727, image: "bancor" },
  FTMUSDT: { id: 4001, image: "fantom" },
  CELOUSDT: { id: 11461, image: "celo" },
  MINAUSDT: { id: 18069, image: "mina-protocol" },
  GLMRUSDT: { id: 22445, image: "moonbeam" },
  MOVRUSDT: { id: 17917, image: "moonriver" },
  ASTARUSDT: { id: 22071, image: "astar" },
  SUSHIUSDT: { id: 12271, image: "sushi" },
  CAKEUSDT: { id: 14541, image: "pancakeswap-token" },
  XVSUSDT: { id: 14779, image: "venus" },
  DODOUSDT: { id: 14685, image: "dodo" },
  REEFUSDT: { id: 13841, image: "reef" },
  BTTUSDT: { id: 13857, image: "bittorrent" },
  HOTUSDT: { id: 2783, image: "holotoken" },
  SCUSDT: { id: 501, image: "siacoin" },
  NMRUSDT: { id: 4433, image: "numeraire" },
  BANDUSDT: { id: 4679, image: "band-protocol" },
  RSRUSDT: { id: 3924, image: "reserve-rights-token" },
  CVCUSDT: { id: 3816, image: "civic" },
  STORJUSDT: { id: 1380, image: "storj" },
  NEXOUSDT: { id: 3693, image: "nexo" },
  PAXUSDT: { id: 3446, image: "paxos-standard" },
  TUSDUSDT: { id: 3447, image: "true-usd" },
  USDCUSDT: { id: 6319, image: "usd-coin" },
  DAIUSDT: { id: 9956, image: "dai" },
  BUSDUSDT: { id: 11967, image: "binance-usd" },
  FRAXUSDT: { id: 23233, image: "frax" },
  TETHEUSDT: { id: 825, image: "tethe" },  // TETHE (Thether) - placeholder, should use actual icon
  USDTUSDT: { id: 325, image: "tether" },
};

function getCoinGeckoIconUrl(symbol: string): string {
  const coin = coinGeckoIds[symbol];
  if (coin) {
    return `https://coin-images.coingecko.com/coins/images/${coin.id}/small/${coin.image}.png`;
  }
  // Fallback to CoinGecko's generic question mark icon
  return `https://coin-images.coingecko.com/coins/images/1/small/question.png`;
}

function mapSignalToTrade(signal: Signal): TradeDisplay {
  const symbol = signal.symbol;
  const currentPrice = signal.current_price ?? null;
  const entryPrice = signal.entry;

  // Calculate PNL if we have current price
  let pnl: number | null = null;
  let pnlPercent: number | null = null;

  if (currentPrice && entryPrice > 0) {
    const isLong = signal.direction === "LONG";
    const priceDiff = isLong ? currentPrice - entryPrice : entryPrice - currentPrice;
    // Use sl_original if available (for trades that hit TP and moved SL to breakeven)
    const slPrice = signal.sl_original || signal.sl;
    const slDistance = Math.abs(entryPrice - slPrice);
    // Express P&L in R-multiples (risk-adjusted)
    pnl = slDistance > 0 ? priceDiff / slDistance : 0;
    // PNL % (without leverage assumption - pure price change percentage)
    pnlPercent = slDistance > 0 ? (priceDiff / slDistance) * 100 : 0;
  }

  return {
    id: signal.id,
    symbol,
    direction: signal.direction,
    strength: signal.strength || "STANDARD",
    entryPrice: signal.entry,
    currentPrice,
    slPrice: signal.sl,
    tp1Price: signal.tp1,
    tp2Price: signal.tp2,
    tp3Price: signal.tp3,
    tp4Price: signal.tp4,
    rr1: signal.rr1,
    rr2: signal.rr2 || 2.0,
    rr3: signal.rr3 || 3.0,
    rrMax: signal.rr_max || 4.0,
    qualityScore: signal.quality_score,
    timeAgo: formatTimeAgo(signal.fired_at),
    firedAt: signal.fired_at,
    iconUrl: getCoinGeckoIconUrl(symbol),
    pnl,
    pnlPercent,
    status: signal.status || "OPEN",
  };
}

function formatTimeAgo(firedAt: string): string {
  try {
    const fired = new Date(firedAt);
    const now = new Date();
    const diffMs = now.getTime() - fired.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d`;
  } catch {
    return "unknown";
  }
}

function getQualityColor(score: number): string {
  if (score >= 70) return "text-emerald-400";
  if (score >= 50) return "text-amber-400";
  return "text-red-400";
}

// Notification helper
function requestNotificationPermission() {
  if (typeof window !== "undefined" && "Notification" in window) {
    Notification.requestPermission();
  }
}

function sendTradeNotification(symbol: string, outcome: string) {
  if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "granted") {
    new Notification("Trade Update", {
      body: `${symbol} has hit ${outcome}!`,
      icon: "/favicon.ico",
    });
  }
}

// Fetch current price from Binance public API
async function fetchBinancePrice(symbol: string): Promise<number | null> {
  try {
    const response = await fetch(`https://api.binance.com/api/v3/ticker/price?symbol=${symbol}`);
    if (!response.ok) return null;
    const data = await response.json();
    if (typeof data.price !== 'string' && typeof data.price !== 'number') return null;
    const price = parseFloat(data.price);
    return isNaN(price) ? null : price;
  } catch {
    return null;
  }
}

// Fetch prices for all trades (deduplicated by symbol)
async function fetchAllPrices(trades: TradeDisplay[]): Promise<Record<string, number>> {
  const uniqueSymbols = [...new Set(trades.map(t => t.symbol))];
  const prices: Record<string, number> = {};
  await Promise.all(
    uniqueSymbols.map(async (symbol) => {
      const price = await fetchBinancePrice(symbol);
      if (price !== null) {
        prices[symbol] = price;
      }
    })
  );
  return prices;
}

export default function LiveTradesPage() {
  const [trades, setTrades] = useState<TradeDisplay[]>([]);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [countdown, setCountdown] = useState(30);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevTradesRef = useRef<TradeDisplay[]>([]);

  const [failedIcons, setFailedIcons] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    try {
      setRefreshing(true);
      const [signals, analyticsData] = await Promise.all([
        getOpenSignals(),
        getAnalyticsSummary(),
      ]);

      const newTrades = signals.map(mapSignalToTrade);

      // Fetch current prices from Binance
      const priceData = await fetchAllPrices(newTrades);
      setPrices(priceData);

      // Update trades with current prices
      const tradesWithPrices = newTrades.map(trade => {
        const currentPrice = priceData[trade.symbol] ?? null;
        if (currentPrice && trade.entryPrice > 0) {
          const isLong = trade.direction === "LONG";
          const priceDiff = isLong ? currentPrice - trade.entryPrice : trade.entryPrice - currentPrice;
          const slDistance = Math.abs(trade.entryPrice - trade.slPrice);
          return {
            ...trade,
            currentPrice,
            pnl: slDistance > 0 ? priceDiff / slDistance : 0,
            pnlPercent: slDistance > 0 ? (priceDiff / slDistance) * 100 : 0,
          };
        }
        return trade;
      });

      // Check for trade outcomes (TP/SL hits) by comparing with previous trades
      // Only trigger notification if we have trades and the API returned data successfully
      if (prevTradesRef.current.length > 0 && tradesWithPrices.length > 0) {
        const closedTrades = prevTradesRef.current.filter(pt => !tradesWithPrices.find(nt => nt.id === pt.id));
        closedTrades.forEach(trade => {
          // Only send notification if we have a valid trade that was actually open
          if (trade.entryPrice > 0 && trade.symbol) {
            sendTradeNotification(trade.symbol, "a target/stop loss");
          }
        });
      }

      prevTradesRef.current = newTrades;
      setTrades(tradesWithPrices);
      setAnalytics(analyticsData);
      setLastUpdated(new Date());
      setCountdown(30);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // Initial data fetch on mount
  const hasFetchedRef = useRef(false);
  useEffect(() => {
    if (!hasFetchedRef.current) {
      hasFetchedRef.current = true;
      fetchData();
      requestNotificationPermission();
    }
  }, [fetchData]);

  // Auto-refresh with countdown - combined into single effect to avoid race condition
  useEffect(() => {
    if (!autoRefresh) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      intervalRef.current = null;
      return;
    }
    let fetching = false;
    const refreshCycle = async () => {
      if (fetching) return;
      fetching = true;
      await fetchData();
      setCountdown(30);
      fetching = false;
    };
    refreshCycle();
    intervalRef.current = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          // Trigger data fetch when countdown reaches 0
          refreshCycle();
          return 30;
        }
        return prev - 1;
      });
    }, 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, fetchData]);

  const activeTrades = trades.length;
  const strongSignals = analytics?.strength_counts?.STRONG ?? 0;
  const standardSignals = analytics?.strength_counts?.STANDARD ?? 0;
  const totalSignals = analytics?.total_signals ?? 0;

  // Find best quality signal among live trades
  const bestTrade = trades.length > 0
    ? trades.reduce((best, t) => t.qualityScore > best.qualityScore ? t : best, trades[0])
    : null;

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white">Live Trades</h1>
              <div className="flex items-center gap-2 px-2.5 py-1 bg-emerald-500/10 rounded-full">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-sm text-emerald-400 font-medium">Live</span>
              </div>
            </div>
            <p className="text-sm text-slate-400 mt-1">
              Real-time monitoring of your active trading signals
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* Active Trades pill */}
            <div className="flex items-center gap-2 px-3 py-2 bg-[#1e293b] rounded-full border border-[#1e293b]">
              <span className="text-sm text-slate-400">Active Trades</span>
              <span className="text-sm font-bold text-white">{activeTrades}</span>
            </div>
            {/* Refresh button */}
            <button
              onClick={fetchData}
              disabled={refreshing}
              className="flex items-center gap-2 px-3 py-2 bg-[#1e293b] border border-[#1e293b] rounded-full text-sm text-white hover:bg-[#2d3748] transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
            {/* Auto-refresh toggle */}
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className="flex items-center gap-2"
            >
              <span className="text-sm text-slate-400">Auto-refresh</span>
              <div className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors ${autoRefresh ? "bg-blue-500" : "bg-slate-600"}`}>
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all ${autoRefresh ? "right-0.5" : "left-0.5"}`} />
              </div>
            </button>
            {/* Countdown */}
            {autoRefresh && <span className="text-sm text-slate-500">{countdown}s</span>}
          </div>
        </div>

        {loading && !trades.length ? (
          <div className="animate-pulse space-y-4 p-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="bg-[#111827] border border-[#1e293b] rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="h-5 w-28 bg-[#1e293b] rounded" />
                    <div className="h-5 w-16 bg-[#1e293b] rounded" />
                  </div>
                  <div className="h-6 w-20 bg-[#1e293b] rounded" />
                </div>
                <div className="grid grid-cols-4 gap-4">
                  <div className="h-12 bg-[#1e293b]/50 rounded" />
                  <div className="h-12 bg-[#1e293b]/50 rounded" />
                  <div className="h-12 bg-[#1e293b]/50 rounded" />
                  <div className="h-12 bg-[#1e293b]/50 rounded" />
                </div>
              </div>
            ))}
          </div>
        ) : error && !trades.length ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-red-400">Error: {error}</div>
          </div>
        ) : (
          <div className="flex flex-col lg:flex-row gap-6">
            {/* Trades List */}
            <div className="flex-1 min-w-0">
              {trades.length === 0 ? (
                <div className="text-center py-12 text-slate-400">
                  No active trades at the moment
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {trades.map((trade) => {
                  const isLong = trade.direction === "LONG";
                  // Calculate SL distance as percentage (absolute value)
                  const slPct = Math.abs(
                    isLong
                      ? ((trade.entryPrice - trade.slPrice) / trade.entryPrice * 100)
                      : ((trade.slPrice - trade.entryPrice) / trade.entryPrice * 100)
                  );

                  return (
                    <Card
                      key={trade.id}
                      className="bg-[#111827] border-[#1e293b] hover:border-emerald-500/30 transition-colors relative overflow-hidden"
                    >
                      {/* Status badge */}
                      <div className="absolute top-4 right-4 z-10">
                        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border mb-4 ${
                          trade.status === "OPEN"
                            ? "bg-emerald-500/10 border-emerald-500/30"
                            : trade.status === "TP1"
                            ? "bg-blue-500/10 border-blue-500/30"
                            : trade.status === "TP2"
                            ? "bg-purple-500/10 border-purple-500/30"
                            : trade.status === "TP3"
                            ? "bg-amber-500/10 border-amber-500/30"
                            : "bg-emerald-500/10 border-emerald-500/30"
                        }`}>
                          <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${
                            trade.status === "OPEN"
                              ? "bg-emerald-500"
                              : trade.status === "TP1"
                              ? "bg-blue-500"
                              : trade.status === "TP2"
                              ? "bg-purple-500"
                              : trade.status === "TP3"
                              ? "bg-amber-500"
                              : "bg-emerald-500"
                          }`} />
                          <span className={`text-[10px] font-bold ${
                            trade.status === "OPEN"
                              ? "text-emerald-400"
                              : trade.status === "TP1"
                              ? "text-blue-400"
                              : trade.status === "TP2"
                              ? "text-purple-400"
                              : trade.status === "TP3"
                              ? "text-amber-400"
                              : "text-emerald-400"
                          }`}>
                            {trade.status}
                          </span>
                        </div>
                      </div>

                      <CardContent className="p-5 pt-10">
                        {/* ROW 1 */}
                        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
                          {/* Left: Coin icon + symbol */}
                          <div className="flex items-center gap-3">
                            <div className="relative w-12 h-12 flex-shrink-0">
                              {failedIcons.has(trade.symbol) ? (
                                <div className="w-12 h-12 rounded-full bg-[#1e293b] flex items-center justify-center text-white font-bold text-lg">
                                  {trade.symbol.charAt(0)}
                                </div>
                              ) : (
                                <img
                                  src={trade.iconUrl}
                                  alt={trade.symbol}
                                  className="w-12 h-12 rounded-full bg-[#1e293b] object-cover"
                                  onError={() => {
                                    setFailedIcons(prev => new Set(prev).add(trade.symbol));
                                  }}
                                />
                              )}
                            </div>
                            <div>
                              <h3 className="text-lg font-bold text-white">{trade.symbol}</h3>
                              <p className="text-xs text-slate-500">{trade.timeAgo} ago</p>
                            </div>
                          </div>

                          {/* Middle-left: Direction + Strength badges */}
                          <div className="flex items-center gap-2 flex-wrap">
                            <Badge
                              variant="outline"
                              className={
                                isLong
                                  ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/10"
                                  : "border-red-500/30 text-red-400 bg-red-500/10"
                              }
                            >
                              {isLong ? (
                                <TrendingUp className="w-3 h-3 mr-1" />
                              ) : (
                                <TrendingDown className="w-3 h-3 mr-1" />
                              )}
                              {trade.direction}
                            </Badge>
                            <Badge
                              variant="outline"
                              className={
                                trade.strength === "STRONG"
                                  ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/10"
                                  : "border-amber-500/30 text-amber-400 bg-amber-500/10"
                              }
                            >
                              {trade.strength}
                            </Badge>
                          </div>

                          {/* Right: RR + Quality */}
                          <div className="text-left sm:text-right">
                            <p className="text-xs text-slate-500">RR Levels</p>
                            <div className="flex items-center gap-1 justify-end">
                              <span className="text-lg font-bold text-emerald-400">1:{trade.rr1}</span>
                              <span className="text-xs text-slate-500">→</span>
                              <span className="text-lg font-bold text-emerald-400">1:{trade.rrMax}</span>
                            </div>
                            <p className="text-[10px] text-slate-500 mt-0.5">
                              TP2: 1:{trade.rr2} | TP3: 1:{trade.rr3}
                            </p>
                          </div>
                        </div>

                        {/* Current Price & PNL */}
                        {trade.currentPrice && (
                          <div className="mt-3 p-3 bg-[#1e293b]/50 rounded-lg">
                            <div className="flex items-center justify-between">
                              <div>
                                <p className="text-xs text-slate-500">Current Price</p>
                                <p className="text-lg font-bold text-white">{formatPrice(trade.currentPrice)}</p>
                              </div>
                              {trade.pnl !== null && trade.pnlPercent !== null && (
                                <div className="text-right">
                                  <p className="text-xs text-slate-500">PNL (10x Leveraged)</p>
                                  <p className={`text-lg font-bold ${trade.pnlPercent >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                    {trade.pnlPercent >= 0 ? "+" : ""}{trade.pnlPercent.toFixed(2)}%
                                  </p>
                                  <p className="text-xs text-slate-500 mt-0.5">
                                    {trade.pnl >= 0 ? "+" : ""}{trade.pnl.toFixed(2)}R
                                  </p>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* ROW 2: Price Levels */}
                        <div className="mt-4">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-slate-500">Price Levels</span>
                            <span className="text-xs text-slate-500">SL Risk: {slPct.toFixed(2)}%</span>
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                            <div className="bg-[#1e293b]/50 rounded-lg p-2">
                              <p className="text-[10px] text-slate-500 uppercase">Entry</p>
                              <p className="text-sm font-bold text-white">{formatPrice(trade.entryPrice)}</p>
                            </div>
                            <div className="bg-red-500/10 rounded-lg p-2">
                              <p className="text-[10px] text-red-400 uppercase">SL</p>
                              <p className="text-sm font-bold text-red-400">{formatPrice(trade.slPrice)}</p>
                            </div>
                            <div className="bg-emerald-500/10 rounded-lg p-2">
                              <p className="text-[10px] text-emerald-400 uppercase">TP1</p>
                              <p className="text-sm font-bold text-emerald-400">{formatPrice(trade.tp1Price)}</p>
                            </div>
                            <div className="bg-emerald-500/10 rounded-lg p-2">
                              <p className="text-[10px] text-emerald-400 uppercase">TP2</p>
                              <p className="text-sm font-bold text-emerald-400">{formatPrice(trade.tp2Price)}</p>
                            </div>
                            <div className="bg-emerald-500/10 rounded-lg p-2">
                              <p className="text-[10px] text-emerald-400 uppercase">TP3</p>
                              <p className="text-sm font-bold text-emerald-400">{formatPrice(trade.tp3Price)}</p>
                            </div>
                            <div className="bg-emerald-500/10 rounded-lg p-2">
                              <p className="text-[10px] text-emerald-400 uppercase">TP4</p>
                              <p className="text-sm font-bold text-emerald-400">{formatPrice(trade.tp4Price)}</p>
                            </div>
                          </div>

                          {/* TP Hit Progress */}
                          {trade.status !== "OPEN" && (
                            <div className="mt-3 p-3 bg-[#1e293b]/30 rounded-lg">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-xs text-slate-400">
                                  {trade.status === "SL" ? "Stop Loss Hit" : "Position Closed"}
                                </span>
                                <span className="text-xs font-bold text-emerald-400">
                                  {trade.status === "SL" ? "" :
                                   trade.status === "TP1" ? "40%" :
                                   trade.status === "TP2" ? "70%" :
                                   trade.status === "TP3" ? "90%" :
                                   trade.status === "TP4" ? "100%" : ""}
                                </span>
                              </div>
                              {trade.status !== "SL" && (
                                <div className="w-full bg-[#1e293b] rounded-full h-2">
                                  <div
                                    className="h-2 rounded-full bg-emerald-500 transition-all duration-500"
                                    style={{
                                      width: trade.status === "TP1" ? "40%" :
                                             trade.status === "TP2" ? "70%" :
                                             trade.status === "TP3" ? "90%" :
                                             trade.status === "TP4" ? "100%" : "0%"
                                    }}
                                  />
                                </div>
                              )}
                            </div>
                          )}

                          {/* Price Progress Toward Next TP */}
                          {trade.currentPrice && trade.status === "OPEN" && (
                            <div className="mt-3 p-3 bg-[#1e293b]/30 rounded-lg">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-xs text-slate-400">Progress to TP1</span>
                                <span className="text-xs text-slate-500">
                                  {formatPrice(trade.currentPrice)} / {formatPrice(trade.tp1Price)}
                                </span>
                              </div>
                              {(() => {
                                const isLong = trade.direction === "LONG";
                                const totalDist = isLong ? trade.tp1Price - trade.entryPrice : trade.entryPrice - trade.tp1Price;
                                const currentDist = isLong ? trade.currentPrice - trade.entryPrice : trade.entryPrice - trade.currentPrice;
                                const progress = totalDist !== 0 ? Math.max(0, Math.min(100, (currentDist / totalDist) * 100)) : 0;
                                return (
                                  <div className="w-full bg-[#1e293b] rounded-full h-2">
                                    <div
                                      className="h-2 rounded-full bg-blue-500 transition-all duration-500"
                                      style={{ width: `${progress}%` }}
                                    />
                                  </div>
                                );
                              })()}
                            </div>
                          )}
                        </div>

                        {/* ROW 3: Stats */}
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mt-4 pt-4 border-t border-[#1e293b]/50 gap-2">
                          <div>
                            <p className="text-xs text-slate-500">RR Levels</p>
                            <p className="text-sm font-bold text-white">
                              TP1: 1:{trade.rr1} | TP2: 1:{trade.rr2} | TP3: 1:{trade.rr3} | TP4: 1:{trade.rrMax}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">Quality Score</p>
                            <p className={`text-sm font-bold ${getQualityColor(trade.qualityScore)}`}>
                              {trade.qualityScore.toFixed(1)} / 100
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-500">Signal Time</p>
                            <p className="text-sm font-bold text-white">{new Date(trade.firedAt).toLocaleString()}</p>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
                </div>
              )}
            </div>

            {/* Right Sidebar */}
            <div className="w-full lg:w-[280px] lg:flex-shrink-0 space-y-4">
              {/* Market Bias */}
              <SidebarCard title="Market Bias">
                <div className="flex items-center justify-center py-4">
                  <div className="relative w-40 h-20">
                    <svg viewBox="0 0 160 80" className="w-full h-full">
                      <defs>
                        <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="#ef4444" />
                          <stop offset="100%" stopColor="#10b981" />
                        </linearGradient>
                      </defs>
                      <path d="M 10 80 A 70 70 0 0 1 150 80" fill="none" stroke="url(#gaugeGrad)" strokeWidth="8" />
                      {/* Needle: biased toward LONG or SHORT based on counts */}
                      {(() => {
                        const longCount = analytics?.direction_counts?.LONG ?? 0;
                        const shortCount = analytics?.direction_counts?.SHORT ?? 0;
                        const total = longCount + shortCount || 1;
                        const ratio = longCount / total;
                        const angle = ratio * Math.PI;
                        const needleLen = 50;
                        const nx = 80 + needleLen * Math.cos(Math.PI - angle);
                        const ny = 80 - needleLen * Math.sin(angle);
                        return (
                          <>
                            <line x1="80" y1="80" x2={nx} y2={ny} stroke="white" strokeWidth="2" />
                            <circle cx="80" cy="80" r="4" fill="white" />
                          </>
                        );
                      })()}
                    </svg>
                  </div>
                </div>
                <div className="flex items-center justify-between px-4">
                  <div className="text-center">
                    <p className="text-xs text-red-400">{analytics?.direction_counts?.SHORT ?? 0} SHORT</p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-emerald-400">{analytics?.direction_counts?.LONG ?? 0} LONG</p>
                  </div>
                </div>
              </SidebarCard>

              {/* Signal Strength */}
              <SidebarCard title="Signal Strength">
                <div className="flex items-center gap-4 py-2">
                  <div className="relative w-20 h-20">
                    <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
                      <circle cx="40" cy="40" r="32" fill="none" stroke="#1e293b" strokeWidth="8" />
                      <circle
                        cx="40"
                        cy="40"
                        r="32"
                        fill="none"
                        stroke="#10b981"
                        strokeWidth="8"
                        strokeDasharray={`${(strongSignals / Math.max(totalSignals, 1)) * 201} 201`}
                      />
                    </svg>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-lg font-bold text-white">
                        {totalSignals > 0 ? Math.round((strongSignals / totalSignals) * 100) : 0}%
                      </span>
                    </div>
                  </div>
                  <div className="flex-1 space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">Strong</span>
                      <span className="text-emerald-400 font-medium">{strongSignals}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">Standard</span>
                      <span className="text-amber-400 font-medium">{standardSignals}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-slate-400">Total</span>
                      <span className="text-white font-medium">{totalSignals}</span>
                    </div>
                  </div>
                </div>
              </SidebarCard>

              {/* Active Trades Summary */}
              <SidebarCard title="Active Trades Summary">
                <div className="space-y-3 py-2">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs text-slate-500">Open Signals</p>
                      <p className="text-lg font-bold text-blue-400">{activeTrades}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-slate-500">Total Signals</p>
                      <p className="text-sm text-slate-400">{totalSignals}</p>
                    </div>
                  </div>
                  <div className="w-full bg-[#1e293b] rounded-full h-2">
                    <div
                      className="h-2 rounded-full bg-blue-500 transition-all duration-500"
                      style={{ width: `${totalSignals > 0 ? (activeTrades / totalSignals) * 100 : 0}%` }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">Avg Quality Score</span>
                    <span className="text-white font-medium">
                      {trades.length > 0
                        ? (trades.reduce((sum, t) => sum + t.qualityScore, 0) / trades.length).toFixed(1)
                        : "0.0"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">Positions</span>
                    <span className="text-white font-medium">{activeTrades}</span>
                  </div>
                  {lastUpdated && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-slate-400">Last Updated</span>
                      <span className="text-slate-500">{lastUpdated.toLocaleTimeString()}</span>
                    </div>
                  )}
                </div>
              </SidebarCard>

              {/* Quick Summary */}
              <SidebarCard title="Quick Summary">
                <div className="space-y-3 py-2">
                  <SummaryRow label="Active Trades" value={String(activeTrades)} />
                  <SummaryRow label="Positions" value={String(activeTrades)} />
                  <SummaryRow label="Strong Signals" value={String(strongSignals)} valueColor="text-emerald-400" />
                  <SummaryRow
                    label="Best Quality"
                    value={bestTrade ? `${bestTrade.symbol} (${bestTrade.qualityScore.toFixed(1)})` : "N/A"}
                    valueColor={bestTrade ? getQualityColor(bestTrade.qualityScore) : "text-slate-400"}
                  />
                  <SummaryRow label="Total Signals" value={String(totalSignals)} valueColor="text-white" />
                </div>
              </SidebarCard>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}

function SidebarCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="bg-[#111827] border-[#1e293b]">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <Info className="w-3.5 h-3.5 text-slate-500 hover:text-slate-400 cursor-pointer" />
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

function SummaryRow({
  label,
  value,
  valueColor = "text-white",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-slate-400">{label}</span>
      <span className={`text-sm font-medium ${valueColor}`}>{value}</span>
    </div>
  );
}

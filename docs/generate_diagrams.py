"""Generate the README diagrams (dark theme, matches the dashboard).

Run from repo root:  python docs/generate_diagrams.py
Outputs: docs/architecture.png, docs/pipeline.png, docs/lifecycle.png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

BG    = "#0B1020"
PANEL = "#121A31"
PANEL2= "#0E1526"
EDGE  = "#2B3860"
TXT   = "#E6EDF7"
SUB   = "#9AA7BD"
CY    = "#22D3EE"
VI    = "#A78BFA"
EM    = "#34D399"
RD    = "#F87171"
AM    = "#FBBF24"
W, H  = 100, 56


def new_fig(title, subtitle, canvas_h=H):
    fig = plt.figure(figsize=(20, canvas_h * 0.2), facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, canvas_h)
    ax.set_facecolor(BG)
    ax.add_patch(plt.Rectangle((0, 0), W, canvas_h, fc=BG, ec="none",
                 zorder=-10))
    ax.axis("off")
    ax.text(2.2, canvas_h - 2.4, title, color=TXT, fontsize=21,
            fontweight="bold", va="center")
    ax.text(2.2, canvas_h - 4.4, subtitle, color=SUB, fontsize=10.5,
            va="center")
    return fig, ax


def panel(ax, x, y, w, h, label, accent):
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle="round,pad=0,rounding_size=1.1",
                 fc=PANEL2, ec=EDGE, lw=1.2, alpha=0.9, zorder=1))
    ax.text(x + 1.2, y + h - 1.5, label, color=accent, fontsize=10.5,
            fontweight="bold", va="center", zorder=2)


def box(ax, x, ytop, w, h, title, lines, accent, tsize=10.0, bsize=8.4):
    """Box whose TOP edge is at ytop."""
    y = ytop - h
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                 boxstyle="round,pad=0,rounding_size=0.8",
                 fc=PANEL, ec=accent, lw=1.5, alpha=0.97, zorder=3))
    ax.add_patch(FancyBboxPatch((x, ytop - 1.15), w, 1.15,
                 boxstyle="round,pad=0,rounding_size=0.8",
                 fc=accent, ec="none", alpha=0.13, zorder=3))
    ax.text(x + 1.0, ytop - 0.62, title, color=accent, fontsize=tsize,
            fontweight="bold", va="center", zorder=4)
    for i, line in enumerate(lines):
        ax.text(x + 1.0, ytop - 2.1 - i * 1.42, line, color=SUB,
                fontsize=bsize, va="center", zorder=4)
    return y


def varrow(ax, x, y1, y2, color=EDGE):
    ax.add_patch(FancyArrowPatch((x, y1), (x, y2), arrowstyle="-|>",
                 mutation_scale=15, color=color, lw=1.7, zorder=2))


def harrow(ax, x1, x2, y, color=EDGE, lw=1.7):
    ax.add_patch(FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>",
                 mutation_scale=16, color=color, lw=lw, zorder=2))


def line(ax, x1, y1, x2, y2, color=EDGE, lw=1.7):
    ax.plot([x1, x2], [y1, y2], color=color, lw=lw, zorder=2)


def arrow(ax, x1, y1, x2, y2, color=EDGE, lw=1.7, rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                 mutation_scale=16, color=color, lw=lw, zorder=2,
                 connectionstyle=f"arc3,rad={rad}"))


def diamond(ax, cx, cy, w, h, text, accent=VI, tsize=9.0):
    ax.add_patch(plt.Polygon(
        [(cx - w/2, cy), (cx, cy + h/2), (cx + w/2, cy), (cx, cy - h/2)],
        closed=True, fc=PANEL, ec=accent, lw=1.5, zorder=3))
    ax.text(cx, cy, text, color=TXT, fontsize=tsize, ha="center",
            va="center", zorder=4)


# ══════════════════════════ 1. ARCHITECTURE ═════════════════════════════

fig, ax = new_fig("TradeEdge — system flow",
                  "4H Supertrend trend-ride · informational signals + optional futures execution")

PTOP = 47.5
panel(ax, 1.5, 3.5, 21, PTOP - 3.5, "SCAN  ·  every 4H at :05 UTC", CY)
panel(ax, 25.5, 3.5, 22, PTOP - 3.5, "DECISION ENGINE", VI)
panel(ax, 50.5, 3.5, 22, PTOP - 3.5, "RISK + QUALITY", AM)
panel(ax, 75.5, 3.5, 23, PTOP - 3.5, "EXECUTION + SERVING", EM)

# col 1
y = box(ax, 3, PTOP - 3.5, 18, 6.0, "Scheduler + watchdog",
        ["main.py · every 4H at :05 UTC", "process lock · Telegram alerts"], CY)
varrow(ax, 12, y, y - 1.4, CY)
y = box(ax, 3, y - 1.4, 18, 7.2, "Universe",
        ["top-100 Binance by volume", "top-100 CoinGecko by mcap",
         "futures-available · exclusions"], CY)
varrow(ax, 12, y, y - 1.4, CY)
y = box(ax, 3, y - 1.4, 18, 6.6, "Fetch 600 closed 4H candles",
        ["thread pool · Retry-After backoff", "live candle always dropped"], CY)
varrow(ax, 12, y, y - 1.4, CY)
box(ax, 3, y - 1.4, 18, 7.6, "Indicators",
    ["Supertrend(10, 3.5) flip", "EMA200 · ATR%",
     "market breadth (share of universe", "above its EMA200) · BTC regime"], CY)

# col 2
y = box(ax, 27, PTOP - 3.5, 19, 7.2, "Exit checks first",
        ["PositionTracker causal replay", "trail / flip / 42-bar time stop",
         "safe across restarts"], VI)
varrow(ax, 36.5, y, y - 1.4, VI)
y = box(ax, 27, y - 1.4, 19, 7.6, "Entry gates (all required)",
        ["flip + close vs EMA200 (long)", "BTC regime bearish (short)",
         "ATR% 0.5–5.0 · not Sunday", "market breadth >= 0.15"], VI)
varrow(ax, 36.5, y, y - 1.4, VI)
y = box(ax, 27, y - 1.4, 19, 7.6, "Signal quality tier",
        ["A  confirmed long", "B  flush / high-breadth short",
         "C, D  weak sets — dropped by", "QUALITY_FILTER=A,B"], VI)
varrow(ax, 36.5, y, y - 1.4, VI)
box(ax, 27, y - 1.4, 19, 6.6, "SignalTracker",
    ["dedup by flip candle · cooldown", "archive to data/signals/"], VI)

# col 3
y = box(ax, 52, PTOP - 3.5, 19, 6.6, "Breadth-scaled risk",
        ["breadth >= 0.30  ->  full 0.5%", "below  ->  half 0.25%",
         "no signals removed"], AM)
varrow(ax, 61.5, y, y - 1.4, AM)
y = box(ax, 52, y - 1.4, 19, 7.6, "Position plan",
        ["entry at next bar open", "initial stop 5xATR (min 2%)",
         "chandelier trail 3.5xATR", "time stop 42 bars (7 days)"], AM)
varrow(ax, 61.5, y, y - 1.4, AM)
y = box(ax, 52, y - 1.4, 19, 6.6, "Virtual positions",
        ["positions.json + trade history", "atomic writes · causal replay",
         "survives restarts"], AM)
varrow(ax, 61.5, y, y - 1.4, AM)
box(ax, 52, y - 1.4, 19, 6.6, "Costs modeled",
    ["0.16% round trip (fee + slip)", "SL-first on intrabar ties",
     "gap-through fills at open"], AM)

# col 4
y = box(ax, 77, PTOP - 3.5, 20, 7.2, "FuturesExecutor (optional)",
        ["EXECUTION_MODE off/dry/live", "MARKET entry + STOP_MARKET trail",
         "reduce-only close on tracker exit"], EM)
varrow(ax, 87, y, y - 1.4, EM)
y = box(ax, 77, y - 1.4, 20, 7.6, "Safety rails",
        ["5x leverage cap · ISOLATED margin", "hard cap 15 concurrent positions",
         "$5 notional · qty step-rounded", "failed stop -> instant flatten"], EM)
varrow(ax, 87, y, y - 1.4, EM)
y = box(ax, 77, y - 1.4, 20, 6.6, "Telegram alerts",
        ["entry / exit / errors / watchdog", "weekly performance digest",
         "orphan-position warnings"], EM)
varrow(ax, 87, y, y - 1.4, EM)
box(ax, 77, y - 1.4, 20, 7.2, "Dashboard",
    ["data/*.json -> FastAPI :8001", "-> Next.js dashboard",
     "signals · positions · backtests", "quality badges on every signal"], EM)

# cross-column arrows
harrow(ax, 21, 27, 44.5, CY)
harrow(ax, 46, 52, 44.5, VI)
harrow(ax, 46, 52, 20.0, VI)
harrow(ax, 71, 77, 44.5, AM)
harrow(ax, 71, 77, 20.0, AM)

# 4H cycle chip across the top
ax.plot([36.5, 87], [49.6, 49.6], color=RD, lw=1.6, zorder=2)
ax.add_patch(FancyArrowPatch((87, 49.6), (87, 44.5), arrowstyle="-|>",
             mutation_scale=15, color=RD, lw=1.6, zorder=2))
ax.text(61, 50.4, "full cycle repeats every 4H — exits first, then entries",
        color=RD, fontsize=9, style="italic", ha="center")

fig.savefig("docs/architecture.png", dpi=170, facecolor=BG)
plt.close(fig)
print("architecture.png done")


# ── 2. ENTRY PIPELINE ────────────────────────────────────────────────────

PH = 74
fig, ax = new_fig("Entry decision pipeline",
                  "every gate must pass - closed 4H candles only",
                  canvas_h=PH)

CX = 32
RAIL = 94

def gate(cx, cy, text, accent=VI, w=26, h=5.4):
    diamond(ax, cx, cy, w, h, text, accent)

NL = chr(10)
gate(CX, 66, "4H candle closes with a Supertrend flip ?", CY, w=30)
varrow(ax, CX, 63.3, 61.9)
gate(CX, 58.5, "ATR% within 0.5 - 5.0 ?")
harrow(ax, CX + 13, RAIL, 58.5, RD)
ax.text(70, 59.3, "no", color=RD, fontsize=8.5, style="italic")
varrow(ax, CX, 55.8, 54.4)
gate(CX, 51, "flip candle opens on Sunday ?")
harrow(ax, CX + 13, RAIL, 51, RD)
ax.text(70, 51.8, "yes", color=RD, fontsize=8.5, style="italic")
varrow(ax, CX, 48.3, 47.1)
gate(CX, 44, "direction of the flip", CY, w=22, h=5)

line(ax, CX - 11, 44, 16, 44); line(ax, 16, 44, 16, 39.6)
varrow(ax, 16, 39.6, 37)
ax.text(23, 45.8, "LONG", color=EM, fontsize=9, fontweight="bold", ha="center")
line(ax, CX + 11, 44, 48, 44); line(ax, 48, 44, 48, 39.6)
varrow(ax, 48, 39.6, 37)
ax.text(43, 45.8, "SHORT", color=RD, fontsize=9, fontweight="bold", ha="center")

gate(16, 33.5, "close above " + NL + "EMA200 ?", w=20, h=5.2)
gate(48, 33.5, "BTC Supertrend " + NL + "bearish ?", w=22, h=5.2)
ax.text(3.2, 33.5, "no = skip", color=RD, fontsize=7.6, style="italic")
ax.text(62, 33.5, "no = skip", color=RD, fontsize=7.6, style="italic")
varrow(ax, 16, 30.9, 29.6)
varrow(ax, 48, 30.9, 29.6)
gate(16, 26, "market breadth " + NL + ">= 0.15 ?", w=20, h=5.2)
gate(48, 26, "market breadth " + NL + ">= 0.15 ?", w=22, h=5.2)
ax.text(3.2, 26, "no = skip", color=RD, fontsize=7.6, style="italic")
ax.text(62, 26, "no = skip", color=RD, fontsize=7.6, style="italic")
varrow(ax, 16, 23.3, 21.9, EM)
varrow(ax, 48, 23.3, 21.9, EM)

gate(CX, 18.5, "quality tier: direction x breadth x symbol", AM, w=30, h=5.2)
line(ax, 16, 23.3, 16, 18.5); line(ax, 16, 18.5, 17, 18.5)
line(ax, 48, 23.3, 48, 18.5); line(ax, 48, 18.5, 47, 18.5)

box(ax, 2, 8, 20, 7, "TAKE - tier A",
    ["confirmed long - full risk 0.5%"], EM)
box(ax, 24, 8, 20, 7, "TAKE - tier B",
    ["flush / high-breadth short - scaled risk"], EM)
box(ax, 46, 8, 24, 7, "NO TRADE this candle",
    ["C: low-breadth long, mid-breadth short", "D: BTC short"], RD)
arrow(ax, CX - 5, 15.7, 12, 8.4, EM)
arrow(ax, CX, 15.7, 34, 8.4, EM)
arrow(ax, CX + 5, 15.7, 58, 8.4, RD)

line(ax, RAIL, 58.5, RAIL, 11.5, RD)
line(ax, RAIL, 11.5, 70, 11.5, RD)

fig.savefig("docs/pipeline.png", dpi=170, facecolor=BG)
plt.close(fig)
print("pipeline.png done")

# ── 3. POSITION LIFECYCLE ────────────────────────────────────────────────

fig, ax = new_fig("Position lifecycle",
                  "the executor mirrors this loop exactly - protective stop always on the exchange")

box(ax, 4, 31.8, 26, 8.2, "ENTRY",
    ["flip candle closes -> enter at next", "candle open (MARKET)",
     "exchange STOP at initial stop 5xATR", "(min 2%) - risk 0.5% / 0.25%"], CY)
box(ax, 36, 31.8, 30, 8.2, "EACH CLOSED 4H CANDLE, IN ORDER",
    ["1  low/high touches the trail stop ?", "2  opposite Supertrend flip ?",
     "3  held 42 bars (7 days) ?", "4  ratchet trail: close -/+ 3.5xATR"], VI)

box(ax, 74, 40, 24, 7.2, "EXIT - trail / stop",
    ["worst case about -1R net of costs", "(median stop distance 13.4%)"], RD)
box(ax, 74, 28, 24, 7.2, "EXIT - opposite flip",
    ["rare: the trend died", "avg -0.41R"], AM)
box(ax, 74, 16, 24, 7.2, "EXIT - time stop",
    ["profit banked before decay", "avg +0.47R - 85% win"], EM)

arrow(ax, 30, 28, 36, 28, CY)
arrow(ax, 66, 30, 74, 36.4, RD, rad=0.12)
arrow(ax, 66, 27.5, 74, 24.6, AM)
arrow(ax, 66, 25.5, 74, 12.4, EM, rad=-0.12)

line(ax, 51, 23.6, 51, 10.5, VI)
line(ax, 51, 10.5, 17, 10.5, VI)
arrow(ax, 17, 10.5, 17, 23.6, CY)
ax.text(34, 8.9, "no exit -> trail ratchets -> repeat next candle",
        color=SUB, fontsize=9.5, style="italic", ha="center")

box(ax, 4, 4.5, 94, 4.6, "3-year backtest exit mix (A/B signals, validated)",
    ["trail/stop 71% of exits · time stop 26% (+0.47R avg, 85% win) · flip 3%  —  win rate 47%, profit factor 1.29-1.59"], EM)

fig.savefig("docs/lifecycle.png", dpi=170, facecolor=BG)
plt.close(fig)
print("lifecycle.png done")

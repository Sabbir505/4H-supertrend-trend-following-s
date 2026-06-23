# Railway Deployment Guide for TradeEdge

This guide walks you through deploying the TradeEdge crypto trading bot to Railway.

## Architecture

```
┌─────────────────┐     ┌─────────────────────────────┐
│   Netlify       │────▶│   Railway                   │
│  (Frontend)     │     │  ┌───────────────────────┐   │
│   FREE          │     │  │  FastAPI API Server   │   │
└─────────────────┘     │  │  + Bot Scheduler      │   │
                        │  │  (single process)     │   │
                        │  └───────────────────────┘   │
                        │         $1-5/month           │
                        └─────────────────────────────┘
```

## Files Created for Deployment

| File | Purpose |
|------|---------|
| `railway.json` | Railway deployment configuration |
| `nixpacks.toml` | Build configuration (Python 3.11, pip install) |
| `Procfile` | Process definition for Railway |
| `railway_server.py` | Combined FastAPI + Bot scheduler entry point |

## Prerequisites

1. **Railway account**: Sign up at [railway.app](https://railway.app)
2. **GitHub account**: Your code needs to be in a GitHub repository
3. **Environment variables**: You'll need your Telegram bot token and chat ID

## Step-by-Step Deployment

### Step 1: Push Code to GitHub

```bash
# Initialize git repo (if not already)
git init

# Add all files
git add .

# Commit
git commit -m "Prepare for Railway deployment"

# Create GitHub repo and push
git remote add origin https://github.com/YOUR_USERNAME/tradeedge.git
git push -u origin main
```

### Step 2: Deploy to Railway

**Option A: Railway Dashboard (Easiest)**

1. Go to [railway.app](https://railway.app) and log in
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Choose your `tradeedge` repository
5. Railway will auto-detect the configuration

**Option B: Railway CLI**

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link to project
railway link

# Deploy
railway up
```

### Step 3: Configure Environment Variables

In Railway Dashboard → Your Project → Variables, add these:

| Variable | Value | Required |
|----------|-------|----------|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather | ✅ Yes |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID | ✅ Yes |
| `TOP_N_COINS` | `100` | ❌ Optional |
| `MAX_SIGNALS_PER_SCAN` | `20` | ❌ Optional |
| `ATR_SL_MULTIPLIER` | `1.0` | ❌ Optional |
| `ATR_TP1_MULTIPLIER` | `1.5` | ❌ Optional |
| `ATR_TP2_MULTIPLIER` | `2.0` | ❌ Optional |
| `ATR_TP3_MULTIPLIER` | `3.0` | ❌ Optional |
| `ATR_TP4_MULTIPLIER` | `4.0` | ❌ Optional |
| `TP1_CLOSE_PERCENT` | `40` | ❌ Optional |
| `TP2_CLOSE_PERCENT` | `30` | ❌ Optional |
| `TP3_CLOSE_PERCENT` | `20` | ❌ Optional |
| `TP4_CLOSE_PERCENT` | `10` | ❌ Optional |
| `LEVERAGE` | `10` | ❌ Optional |
| `SIGNAL_EXPIRATION_MINUTES` | `10080` | ❌ Optional |
| `MIN_QUALITY_SCORE` | `60` | ❌ Optional |
| `TRADING_START_HOUR` | `14` | ❌ Optional |
| `TRADING_END_HOUR` | `22` | ❌ Optional |
| `SYMBOL_WIN_RATE_MIN` | `0.40` | ❌ Optional |
| `ADAPTIVE_TP_ENABLED` | `true` | ❌ Optional |

> **Note**: The `.env` file is NOT committed to GitHub. You MUST set these in Railway Dashboard.

### Step 4: Add a Volume (Persistent Storage)

Your bot writes signal data to `data/signals/`. On Railway, you need a volume for persistence:

1. Railway Dashboard → Your Service → **Volumes**
2. Click **"New Volume"**
3. Mount path: `/app/data`
4. Size: 1GB (minimum)

Then update your code to use `/app/data` as the data directory (already configured in `railway_server.py` if needed).

### Step 5: Deploy Frontend to Netlify

```bash
cd frontend

# Install Netlify CLI
npm install -g netlify-cli

# Login
netlify login

# Build
npm run build

# Deploy
netlify deploy --prod --dir=.next
```

**Or use GitHub + Netlify auto-deploy:**

1. Go to [netlify.com](https://netlify.com)
2. **Add new site** → **Import from GitHub**
3. Select your repo
4. Base directory: `frontend`
5. Build command: `npm run build`
6. Publish directory: `.next`
7. Add environment variable: `NEXT_PUBLIC_API_URL=https://your-railway-app.up.railway.app`

## How It Works

1. **Single Process**: `railway_server.py` runs both the FastAPI API and the bot scheduler in one process
2. **Background Thread**: The bot scheduler runs in a daemon thread alongside the API server
3. **WebSocket Monitoring**: The tracker monitors open positions via WebSocket
4. **REST Fallback**: Every 5 minutes, a scheduled check runs as backup
5. **Telegram Alerts**: Signals are sent to your Telegram channel automatically

## Monitoring

### Railway Dashboard
- View logs: Railway Dashboard → Your Service → **Logs**
- View metrics: Railway Dashboard → Your Service → **Metrics**
- View deployments: Railway Dashboard → Your Service → **Deployments**

### Health Check
Your API root endpoint is available at:
```
https://your-app.up.railway.app/
```
Response: `{"message": "TradeEdge API", "version": "1.0.0"}`

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/signals/open` | Open signals (live trades) |
| `GET /api/signals/closed` | Closed signals (history) |
| `GET /api/dashboard/stats` | Dashboard statistics |
| `GET /api/live-trades` | Live trades with current prices |
| `GET /api/analytics/summary` | Analytics data |
| `GET /api/market/calendar` | Economic calendar |
| `GET /api/market/news` | Crypto news |
| `GET /api/market/events` | Token events |
| `GET /api/market/impact` | Event impact analysis |

## Troubleshooting

### Bot not sending signals?
- Check Railway logs for errors
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are correct
- Ensure trading hours (UTC) are configured correctly

### API not responding?
- Check if the service is running in Railway Dashboard
- Verify the `PORT` environment variable is set (Railway sets this automatically)
- Check CORS settings in `api_server.py`

### Data not persisting?
- Make sure you added a Volume in Railway
- Verify the volume is mounted at the correct path
- Check that the app has write permissions

### High memory usage?
- Railway free tier has 512MB RAM
- If you hit limits, consider upgrading to Hobby plan ($5/month)
- Or optimize by reducing `TOP_N_COINS` from 100 to 50

## Cost Estimate

| Plan | Cost | Resources |
|------|------|-----------|
| **Free Trial** | $0 (30 days) | $5 credit |
| **Hobby** | $5/month | 1 vCPU, 0.5GB RAM, 0.5GB storage |
| **Pro** | $20/month | Up to 48 vCPU, 48GB RAM |

For this project, **Hobby plan ($5/month)** is sufficient.

## Updating Your Deployment

```bash
# Make changes locally
git add .
git commit -m "Update bot logic"
git push origin main

# Railway auto-deploys from GitHub
# Or manually: railway up
```

## Next Steps

1. ✅ Deploy backend to Railway
2. ✅ Deploy frontend to Netlify
3. ✅ Set environment variables
4. ✅ Add persistent volume
5. 🔄 Monitor and optimize

## Support

- Railway Docs: [docs.railway.app](https://docs.railway.app)
- Railway Discord: [discord.gg/railway](https://discord.gg/railway)
- Netlify Docs: [docs.netlify.com](https://docs.netlify.com)

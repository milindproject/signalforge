# SignalForge — Live India Trading Signals
## RSI Avg-Cross + BOBtc Strategy | Free Realtime NSE/BSE Data

---

## What You Get
- **Free Python backend** deployed on Render.com — fetches live data from Yahoo Finance
- **Full trading dashboard** (HTML file) — runs in any browser, connects to your backend
- **Realtime OHLCV candles** for all NSE/BSE indices, stocks, ETFs, commodities, global indices
- **RSI Avg-Cross 4-rule signal engine** (your custom strategy)
- **BOBtc/BCTB indicator** (ATR trailing stop)
- **All-timeframe signal table** (5m, 15m, 30m, 1H, 1D, 1W)

---

## Deployment — Step by Step (15 minutes, free)

### Step 1 — Create GitHub Repository
1. Go to https://github.com → Sign in (or create free account)
2. Click **New repository** → Name it `signalforge-api`
3. Set to **Public** → Click **Create repository**
4. Upload these 4 files from the `backend/` folder:
   - `app.py`
   - `requirements.txt`
   - `render.yaml`
   - `Procfile`

### Step 2 — Deploy on Render.com (Free)
1. Go to https://render.com → Sign in with GitHub
2. Click **New +** → **Web Service**
3. Select your `signalforge-api` repository
4. Render auto-detects settings from `render.yaml`. Click **Deploy Web Service**
5. Wait 3–5 minutes for the build to complete
6. Your URL will be: `https://signalforge-api.onrender.com` (or similar)
7. Copy this URL

### Step 3 — Open the Dashboard
1. Open `frontend/index.html` in Chrome/Edge/Firefox
2. Paste your Render.com URL in the **Backend URL** field at the top
3. Click **Test Connection** — you should see ✓ Connected
4. Select any symbol → click **Analyze** → live signals appear!

---

## API Endpoints (your backend)

Once deployed, your backend supports these endpoints:

| Endpoint | Description | Example |
|----------|-------------|---------|
| `GET /` | Service info | `/` |
| `GET /health` | Health check | `/health` |
| `GET /candles` | OHLCV candle data | `/candles?symbol=RELIANCE.NS&interval=1d` |
| `GET /quote` | Latest quote | `/quote?symbol=^NSEI` |
| `GET /multi` | Multiple symbols | `/multi?symbols=^NSEI,^NSEBANK,RELIANCE.NS&interval=1d` |
| `GET /search` | Symbol search | `/search?q=reliance` |

### Supported intervals: `5m`, `15m`, `30m`, `1h`, `1d`, `1wk`

### Example API calls:
```
# Nifty 50 daily candles
https://your-app.onrender.com/candles?symbol=^NSEI&interval=1d

# RELIANCE 15-minute candles
https://your-app.onrender.com/candles?symbol=RELIANCE.NS&interval=15m

# BankNifty hourly candles
https://your-app.onrender.com/candles?symbol=^NSEBANK&interval=1h

# Multiple symbols at once
https://your-app.onrender.com/multi?symbols=^NSEI,^NSEBANK,^BSESN&interval=1d

# Latest quote
https://your-app.onrender.com/quote?symbol=TCS.NS
```

---

## Important Notes

### Render Free Tier — Cold Start
Render's free tier puts your service to sleep after 15 minutes of inactivity.
The first request after sleep takes **20–30 seconds** to wake up.
Solution: Just click Analyze again if the first request times out.

To avoid cold starts, upgrade to Render's Starter plan ($7/month) or
ping your service every 10 minutes using a free cron service like cron-job.org:
- URL to ping: `https://your-app.onrender.com/health`
- Interval: Every 10 minutes

### Yahoo Finance Data
- NSE/BSE stocks: use `.NS` suffix (e.g., `RELIANCE.NS`)
- BSE stocks: use `.BO` suffix (e.g., `RELIANCE.BO`)
- NSE indices: use `^` prefix (e.g., `^NSEI`, `^NSEBANK`)
- BSE Sensex: `^BSESN`
- Intraday data (5m, 15m, 30m) is only available for the last 5 days
- Daily data (`1d`) is available for 6 months
- Weekly data (`1wk`) is available for 2 years

### Market Hours (IST)
- NSE/BSE: Monday–Friday, 9:15 AM – 3:30 PM IST
- Outside market hours, last available candle data is returned

---

## Symbols Reference

### Key NSE Indices
| Symbol | Index |
|--------|-------|
| `^NSEI` | Nifty 50 |
| `^NSEBANK` | Bank Nifty |
| `^CNXFINANCE` | Nifty Fin Services (FinNifty) |
| `^CNXIT` | Nifty IT |
| `^CNXAUTO` | Nifty Auto |
| `^CNXFMCG` | Nifty FMCG |
| `^CNXPHARMA` | Nifty Pharma |
| `^CNXMETAL` | Nifty Metal |
| `^CNXPSUBANK` | Nifty PSU Bank |
| `^INDIAVIX` | India VIX |
| `^BSESN` | BSE Sensex |

### Key NSE Stocks
| Symbol | Company |
|--------|---------|
| `RELIANCE.NS` | Reliance Industries |
| `TCS.NS` | Tata Consultancy Services |
| `HDFCBANK.NS` | HDFC Bank |
| `ICICIBANK.NS` | ICICI Bank |
| `INFY.NS` | Infosys |
| `SBIN.NS` | State Bank of India |
| `BHARTIARTL.NS` | Bharti Airtel |
| `KOTAKBANK.NS` | Kotak Bank |
| `AXISBANK.NS` | Axis Bank |
| `LT.NS` | Larsen & Toubro |

---

## Signal Logic

### RSI Avg-Cross Rules (4 Rules)
| Rule | Condition | Signal |
|------|-----------|--------|
| R1 | RSI line is **below** Average line | SELL |
| R2 | RSI line is **above** Average line | BUY |
| R3 | Average line is **below 40** | SELL (strong) |
| R4 | Average line is **above 60** | BUY (strong) |

- Rules 3 & 4 carry double weight
- Combined confidence: 92% (both agree) → 75% (Avg zone only) → 60% (crossover only)

### BOBtc / BCTB Indicator
- ATR Period: 22
- ATR Multiplier: 3.0
- Generates Buy/Sell signals based on ATR trailing stop direction changes

### Combined Signal
- Both BUY → BUY with high confidence
- Both SELL → SELL with high confidence
- Mixed → whichever has higher weight wins

---

## Troubleshooting

**"Cannot reach" error** — Make sure your Render.com deployment is complete and the URL is correct.

**"No data returned"** — Market may be closed. Try `1d` or `1wk` interval which returns historical data.

**Timeout on first request** — Render free tier cold start. Wait 30 seconds and try again.

**Intraday (5m/15m) shows no data on weekend** — Normal. Yahoo Finance only provides intraday data during active market sessions.

---

## Tech Stack
- **Backend**: Python 3.11, Flask, yfinance, pandas, gunicorn
- **Frontend**: Vanilla HTML/CSS/JS, Chart.js
- **Data**: Yahoo Finance (free, no API key)
- **Hosting**: Render.com (free tier)
- **Cost**: ₹0 / $0 forever

---

*Built with ❤️ — SignalForge v10 | RSI Avg-Cross + BOBtc Strategy*

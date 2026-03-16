"""
SignalForge Backend v2 - Render.com free deployment
Uses Yahoo Finance HTTP API directly (requests library).
No yfinance cookie/crumb issues. Works reliably on cloud servers.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
from datetime import datetime, timezone
import traceback
import time

app = Flask(__name__)
CORS(app, origins="*")

# ── Interval to Yahoo Finance params ────────────────────────────────────────
# Yahoo Finance v8/finance/chart params
INTERVAL_MAP = {
    "5m":  {"interval": "5m",  "range": "5d"},
    "15m": {"interval": "15m", "range": "5d"},
    "30m": {"interval": "30m", "range": "5d"},
    "1h":  {"interval": "60m", "range": "1mo"},
    "1d":  {"interval": "1d",  "range": "1y"},
    "1wk": {"interval": "1wk", "range": "2y"},
}

# Realistic browser headers to avoid Yahoo blocking cloud server IPs
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://finance.yahoo.com",
    "Referer": "https://finance.yahoo.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

def fetch_yahoo(symbol, interval, range_period, retries=2):
    """
    Fetch OHLCV data directly from Yahoo Finance v8 chart API.
    Returns list of candle dicts or raises an exception.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "interval":       interval,
        "range":          range_period,
        "includePrePost": "false",
        "events":         "div,splits",
        "corsDomain":     "finance.yahoo.com",
    }

    last_err = None
    # Try query1 then query2
    for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
        for attempt in range(retries):
            try:
                url = f"{base}/v8/finance/chart/{symbol}"
                resp = requests.get(url, params=params, headers=HEADERS, timeout=20)

                if resp.status_code == 429:
                    time.sleep(2)
                    continue
                if resp.status_code == 404:
                    raise ValueError(f"Symbol '{symbol}' not found on Yahoo Finance.")
                if resp.status_code != 200:
                    raise ValueError(f"Yahoo Finance returned HTTP {resp.status_code}.")

                data = resp.json()

                # Check for Yahoo-level error
                if data.get("chart", {}).get("error"):
                    err = data["chart"]["error"]
                    raise ValueError(f"Yahoo Finance error: {err.get('description', str(err))}")

                result = data.get("chart", {}).get("result", [])
                if not result or not result[0].get("timestamp"):
                    raise ValueError(
                        f"No data returned for {symbol}. "
                        "This can happen when: (1) market is closed for intraday intervals, "
                        "(2) symbol is incorrect, or (3) Yahoo Finance is temporarily blocking this IP. "
                        "Try switching to 1D or 1W timeframe."
                    )

                res       = result[0]
                timestamps = res["timestamp"]
                quote     = res["indicators"]["quote"][0]
                opens     = quote.get("open",   [])
                highs     = quote.get("high",   [])
                lows      = quote.get("low",    [])
                closes    = quote.get("close",  [])
                volumes   = quote.get("volume", [])
                tz        = res.get("meta", {}).get("exchangeTimezoneName", "Asia/Kolkata")

                candles = []
                for i, ts in enumerate(timestamps):
                    try:
                        c = closes[i] if i < len(closes) else None
                        o = opens[i]  if i < len(opens)  else None
                        h = highs[i]  if i < len(highs)  else None
                        l = lows[i]   if i < len(lows)   else None
                        v = volumes[i] if i < len(volumes) else 0

                        if c is None or o is None or c <= 0 or o <= 0:
                            continue

                        dt_obj = datetime.fromtimestamp(ts, tz=timezone.utc)
                        if interval in ("1d", "1wk"):
                            dt_str = dt_obj.strftime("%Y-%m-%d")
                        else:
                            # Convert to IST
                            import zoneinfo
                            ist = dt_obj.astimezone(zoneinfo.ZoneInfo("Asia/Kolkata"))
                            dt_str = ist.strftime("%Y-%m-%d %H:%M")

                        candles.append({
                            "dt": dt_str,
                            "o":  round(float(o), 4),
                            "h":  round(float(h), 4) if h else round(float(c), 4),
                            "l":  round(float(l), 4) if l else round(float(c), 4),
                            "c":  round(float(c), 4),
                            "v":  int(v) if v else 0,
                        })
                    except Exception:
                        continue

                if not candles:
                    raise ValueError(
                        f"All candles were null for {symbol}. "
                        "Try 1D or 1W timeframe."
                    )

                return candles[-100:]  # Last 100 candles

            except ValueError:
                raise
            except Exception as e:
                last_err = e
                time.sleep(1)

    raise ValueError(f"Failed to fetch data after retries. Last error: {last_err}")


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "service":   "SignalForge Data API v2",
        "status":    "running",
        "data_source": "Yahoo Finance Direct HTTP",
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@app.route("/candles")
def candles():
    symbol   = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "1d").strip()

    if not symbol:
        return jsonify({"error": "symbol parameter is required"}), 400

    # Normalise interval
    iv_norm = {"60m": "1h", "h": "1h", "d": "1d", "w": "1wk", "week": "1wk"}
    interval = iv_norm.get(interval, interval)

    if interval not in INTERVAL_MAP:
        return jsonify({
            "error": f"Invalid interval '{interval}'. Must be one of: {', '.join(INTERVAL_MAP)}"
        }), 400

    iv_params   = INTERVAL_MAP[interval]
    yf_interval = iv_params["interval"]
    yf_range    = iv_params["range"]

    try:
        candles_list = fetch_yahoo(symbol, yf_interval, yf_range)
        return jsonify({
            "symbol":   symbol,
            "interval": interval,
            "count":    len(candles_list),
            "candles":  candles_list,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()[-400:]}), 500


@app.route("/quote")
def quote():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol required"}), 400
    try:
        candles_list = fetch_yahoo(symbol, "1d", "5d")
        if len(candles_list) < 1:
            return jsonify({"error": f"No data for {symbol}"}), 404
        last = candles_list[-1]
        prev = candles_list[-2] if len(candles_list) >= 2 else last
        c, pc = last["c"], prev["c"]
        return jsonify({
            "symbol":     symbol,
            "last_price": c,
            "open":       last["o"],
            "high":       last["h"],
            "low":        last["l"],
            "prev_close": pc,
            "change":     round(c - pc, 4),
            "change_pct": round(((c - pc) / pc) * 100, 2) if pc else 0,
            "volume":     last["v"],
            "timestamp":  datetime.utcnow().isoformat(),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/multi")
def multi():
    symbols_raw = request.args.get("symbols", "").strip()
    interval    = request.args.get("interval", "1d").strip()
    if not symbols_raw:
        return jsonify({"error": "symbols parameter required"}), 400

    symbols  = [s.strip() for s in symbols_raw.split(",") if s.strip()][:20]
    iv_norm  = {"60m": "1h"}
    interval = iv_norm.get(interval, interval)
    if interval not in INTERVAL_MAP:
        interval = "1d"

    iv_params   = INTERVAL_MAP[interval]
    yf_interval = iv_params["interval"]
    yf_range    = iv_params["range"]
    results     = {}

    for sym in symbols:
        try:
            cl = fetch_yahoo(sym, yf_interval, yf_range)
            last = cl[-1]; prev = cl[-2] if len(cl) >= 2 else last
            c, pc = last["c"], prev["c"]
            results[sym] = {
                "last_price": c,
                "open":       last["o"],
                "high":       last["h"],
                "low":        last["l"],
                "prev_close": pc,
                "change":     round(c - pc, 4),
                "change_pct": round(((c - pc) / pc) * 100, 2) if pc else 0,
                "volume":     last["v"],
                "candles":    cl,
            }
        except Exception as e:
            results[sym] = {"error": str(e)}

    return jsonify({
        "interval":  interval,
        "count":     len(symbols),
        "data":      results,
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"error": "q required"}), 400

    DB = [
        # NSE Indices
        {"symbol":"^NSEI",        "name":"Nifty 50 Index",           "exchange":"NSE",    "type":"Index"},
        {"symbol":"^NSEBANK",     "name":"Bank Nifty Index",          "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXFINANCE",  "name":"Nifty Fin Services",        "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXIT",       "name":"Nifty IT Index",            "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXAUTO",     "name":"Nifty Auto Index",          "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXFMCG",     "name":"Nifty FMCG Index",          "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXPHARMA",   "name":"Nifty Pharma Index",        "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXMETAL",    "name":"Nifty Metal Index",         "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXREALTY",   "name":"Nifty Realty Index",        "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXENERGY",   "name":"Nifty Energy Index",        "exchange":"NSE",    "type":"Index"},
        {"symbol":"^CNXPSUBANK",  "name":"Nifty PSU Bank Index",      "exchange":"NSE",    "type":"Index"},
        {"symbol":"^INDIAVIX",    "name":"India VIX",                 "exchange":"NSE",    "type":"Index"},
        # BSE Indices
        {"symbol":"^BSESN",       "name":"BSE Sensex",                "exchange":"BSE",    "type":"Index"},
        {"symbol":"^BSEMD",       "name":"BSE Midcap",                "exchange":"BSE",    "type":"Index"},
        {"symbol":"^BSESML",      "name":"BSE Smallcap",              "exchange":"BSE",    "type":"Index"},
        {"symbol":"^BANKEX",      "name":"BSE Bankex",                "exchange":"BSE",    "type":"Index"},
        {"symbol":"^BSEIT",       "name":"BSE IT",                    "exchange":"BSE",    "type":"Index"},
        # NSE Stocks
        {"symbol":"RELIANCE.NS",  "name":"Reliance Industries",       "exchange":"NSE",    "type":"Stock"},
        {"symbol":"TCS.NS",       "name":"Tata Consultancy Services", "exchange":"NSE",    "type":"Stock"},
        {"symbol":"HDFCBANK.NS",  "name":"HDFC Bank",                 "exchange":"NSE",    "type":"Stock"},
        {"symbol":"ICICIBANK.NS", "name":"ICICI Bank",                "exchange":"NSE",    "type":"Stock"},
        {"symbol":"INFY.NS",      "name":"Infosys",                   "exchange":"NSE",    "type":"Stock"},
        {"symbol":"SBIN.NS",      "name":"State Bank of India",       "exchange":"NSE",    "type":"Stock"},
        {"symbol":"ITC.NS",       "name":"ITC Ltd",                   "exchange":"NSE",    "type":"Stock"},
        {"symbol":"BHARTIARTL.NS","name":"Bharti Airtel",             "exchange":"NSE",    "type":"Stock"},
        {"symbol":"LT.NS",        "name":"Larsen and Toubro",         "exchange":"NSE",    "type":"Stock"},
        {"symbol":"HCLTECH.NS",   "name":"HCL Technologies",          "exchange":"NSE",    "type":"Stock"},
        {"symbol":"WIPRO.NS",     "name":"Wipro",                     "exchange":"NSE",    "type":"Stock"},
        {"symbol":"KOTAKBANK.NS", "name":"Kotak Mahindra Bank",       "exchange":"NSE",    "type":"Stock"},
        {"symbol":"HINDUNILVR.NS","name":"Hindustan Unilever",        "exchange":"NSE",    "type":"Stock"},
        {"symbol":"BAJFINANCE.NS","name":"Bajaj Finance",             "exchange":"NSE",    "type":"Stock"},
        {"symbol":"AXISBANK.NS",  "name":"Axis Bank",                 "exchange":"NSE",    "type":"Stock"},
        {"symbol":"MARUTI.NS",    "name":"Maruti Suzuki",             "exchange":"NSE",    "type":"Stock"},
        {"symbol":"SUNPHARMA.NS", "name":"Sun Pharma",                "exchange":"NSE",    "type":"Stock"},
        {"symbol":"TITAN.NS",     "name":"Titan Company",             "exchange":"NSE",    "type":"Stock"},
        {"symbol":"NTPC.NS",      "name":"NTPC",                      "exchange":"NSE",    "type":"Stock"},
        {"symbol":"TATAMOTORS.NS","name":"Tata Motors",               "exchange":"NSE",    "type":"Stock"},
        {"symbol":"TATASTEEL.NS", "name":"Tata Steel",                "exchange":"NSE",    "type":"Stock"},
        {"symbol":"ONGC.NS",      "name":"ONGC",                      "exchange":"NSE",    "type":"Stock"},
        {"symbol":"JSWSTEEL.NS",  "name":"JSW Steel",                 "exchange":"NSE",    "type":"Stock"},
        {"symbol":"POWERGRID.NS", "name":"Power Grid Corporation",    "exchange":"NSE",    "type":"Stock"},
        {"symbol":"HINDALCO.NS",  "name":"Hindalco Industries",       "exchange":"NSE",    "type":"Stock"},
        {"symbol":"ADANIENT.NS",  "name":"Adani Enterprises",         "exchange":"NSE",    "type":"Stock"},
        {"symbol":"ZOMATO.NS",    "name":"Zomato",                    "exchange":"NSE",    "type":"Stock"},
        {"symbol":"IRCTC.NS",     "name":"IRCTC",                     "exchange":"NSE",    "type":"Stock"},
        {"symbol":"TATAPOWER.NS", "name":"Tata Power",                "exchange":"NSE",    "type":"Stock"},
        {"symbol":"INDUSINDBK.NS","name":"IndusInd Bank",             "exchange":"NSE",    "type":"Stock"},
        {"symbol":"PNB.NS",       "name":"Punjab National Bank",      "exchange":"NSE",    "type":"Stock"},
        {"symbol":"BANKBARODA.NS","name":"Bank of Baroda",            "exchange":"NSE",    "type":"Stock"},
        {"symbol":"CANBK.NS",     "name":"Canara Bank",               "exchange":"NSE",    "type":"Stock"},
        {"symbol":"IDFCFIRSTB.NS","name":"IDFC First Bank",           "exchange":"NSE",    "type":"Stock"},
        # ETFs
        {"symbol":"NIFTYBEES.NS", "name":"Nifty 50 BeES ETF",         "exchange":"NSE",    "type":"ETF"},
        {"symbol":"BANKBEES.NS",  "name":"Bank Nifty BeES ETF",       "exchange":"NSE",    "type":"ETF"},
        {"symbol":"GOLDBEES.NS",  "name":"Gold BeES ETF",             "exchange":"NSE",    "type":"ETF"},
        # Commodities
        {"symbol":"GC=F",         "name":"Gold Futures COMEX",        "exchange":"COMEX",  "type":"Commodity"},
        {"symbol":"CL=F",         "name":"WTI Crude Oil Futures",     "exchange":"NYMEX",  "type":"Commodity"},
        {"symbol":"SI=F",         "name":"Silver Futures",            "exchange":"COMEX",  "type":"Commodity"},
        {"symbol":"NG=F",         "name":"Natural Gas Futures",       "exchange":"NYMEX",  "type":"Commodity"},
        {"symbol":"XAU=X",        "name":"Gold Spot USD",             "exchange":"Forex",  "type":"Forex"},
        # Global
        {"symbol":"^GSPC",        "name":"S&P 500 Index",             "exchange":"NYSE",   "type":"Index"},
        {"symbol":"^IXIC",        "name":"Nasdaq Composite",          "exchange":"NASDAQ", "type":"Index"},
        {"symbol":"^DJI",         "name":"Dow Jones Industrial",      "exchange":"NYSE",   "type":"Index"},
        {"symbol":"^N225",        "name":"Nikkei 225 Japan",          "exchange":"TSE",    "type":"Index"},
        {"symbol":"^GDAXI",       "name":"DAX Germany",               "exchange":"XETRA",  "type":"Index"},
        {"symbol":"BTC-USD",      "name":"Bitcoin USD",               "exchange":"Crypto", "type":"Crypto"},
        {"symbol":"ETH-USD",      "name":"Ethereum USD",              "exchange":"Crypto", "type":"Crypto"},
        {"symbol":"INR=X",        "name":"USD Indian Rupee",          "exchange":"Forex",  "type":"Forex"},
        {"symbol":"EURUSD=X",     "name":"Euro US Dollar",            "exchange":"Forex",  "type":"Forex"},
    ]

    results = [s for s in DB if q in s["symbol"].lower() or q in s["name"].lower()][:15]
    return jsonify({"query": q, "count": len(results), "results": results})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)

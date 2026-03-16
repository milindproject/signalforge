"""
SignalForge Backend - Render.com free deployment
Fetches NSE/BSE/Global data from Yahoo Finance server-side.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime
import traceback

app = Flask(__name__)
CORS(app, origins="*")

# Index symbols - these need longer periods and daily fallback
INDEX_SYMBOLS = {
    '^NSEI', '^NSEBANK', '^BSESN', '^CNXFINANCE', '^CNXIT', '^CNXAUTO',
    '^CNXFMCG', '^CNXPHARMA', '^CNXMETAL', '^CNXREALTY', '^CNXENERGY',
    '^CNXPSUBANK', '^INDIAVIX', '^BSEMD', '^BSESML', '^BANKEX', '^BSEIT',
    '^BSEHC', '^CNX100', '^CNX500', '^NSEMDCP50', '^CNXSC', '^GSPC',
    '^IXIC', '^DJI', '^N225', '^GDAXI', '^FTSE', '^HSI'
}

# For each interval, the period to fetch
INTERVAL_PERIOD = {
    "1m":  "1d",
    "5m":  "5d",
    "15m": "5d",
    "30m": "5d",
    "1h":  "1mo",
    "1d":  "1y",
    "1wk": "2y",
}

def smart_fetch(symbol, interval):
    """
    Fetch candles with automatic fallback:
    - Try requested interval first
    - If empty (market closed / index restriction), fall back to 1d
    - Always return at least some data
    """
    is_index = symbol in INDEX_SYMBOLS or symbol.startswith('^')
    period = INTERVAL_PERIOD.get(interval, "1mo")

    # For indices with intraday intervals, Yahoo Finance is unreliable
    # Try requested first, then fall back to daily
    intervals_to_try = [interval]
    if is_index and interval in ("1m", "5m", "15m", "30m", "1h"):
        intervals_to_try = [interval, "1d"]  # fallback to daily

    df = None
    used_interval = interval

    for iv in intervals_to_try:
        p = INTERVAL_PERIOD.get(iv, "1mo")
        try:
            ticker = yf.Ticker(symbol)
            result = ticker.history(period=p, interval=iv, auto_adjust=True)
            if result is not None and not result.empty:
                df = result
                used_interval = iv
                break
        except Exception:
            continue

    return df, used_interval


def df_to_candles(df, interval):
    """Convert a yfinance DataFrame to our candle list format."""
    candles = []
    for ts, row in df.iterrows():
        try:
            if interval in ("1d", "1wk"):
                dt_str = ts.strftime("%Y-%m-%d") if hasattr(ts, 'strftime') else str(ts)[:10]
            else:
                ist = ts.tz_convert("Asia/Kolkata") if (hasattr(ts, 'tzinfo') and ts.tzinfo) else ts
                dt_str = ist.strftime("%Y-%m-%d %H:%M") if hasattr(ist, 'strftime') else str(ts)[:16]

            o = round(float(row["Open"]),  4) if pd.notna(row.get("Open"))  else None
            h = round(float(row["High"]),  4) if pd.notna(row.get("High"))  else None
            l = round(float(row["Low"]),   4) if pd.notna(row.get("Low"))   else None
            c = round(float(row["Close"]), 4) if pd.notna(row.get("Close")) else None
            v = int(row["Volume"])             if pd.notna(row.get("Volume")) else 0

            if c is None or c <= 0 or o is None or o <= 0:
                continue

            candles.append({"dt": dt_str, "o": o, "h": h or c, "l": l or c, "c": c, "v": v})
        except Exception:
            continue

    return candles


@app.route("/")
def index():
    return jsonify({
        "service": "SignalForge Data API",
        "status":  "running",
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

    # Normalise interval names from frontend
    iv_map = {"15m": "15m", "5m": "5m", "30m": "30m", "1h": "1h", "1d": "1d", "1wk": "1wk"}
    interval = iv_map.get(interval, interval)
    if interval not in INTERVAL_PERIOD:
        return jsonify({"error": f"interval must be one of: {', '.join(INTERVAL_PERIOD)}"}), 400

    try:
        df, used_interval = smart_fetch(symbol, interval)

        if df is None or df.empty:
            is_index = symbol.startswith('^')
            hint = ""
            if is_index:
                hint = " Indices sometimes have limited intraday data. Try 1D timeframe."
            return jsonify({
                "error": f"No data returned for {symbol}.{hint} If market is closed, try 1D or 1W timeframe."
            }), 404

        candles_list = df_to_candles(df, used_interval)

        if not candles_list:
            return jsonify({"error": f"All candles were null for {symbol}. Try 1D timeframe."}), 404

        # Return last 100 candles
        candles_list = candles_list[-100:]

        return jsonify({
            "symbol":        symbol,
            "interval":      used_interval,
            "interval_note": f"Requested: {interval}, Used: {used_interval}" if used_interval != interval else interval,
            "count":         len(candles_list),
            "candles":       candles_list
        })

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()[-500:]}), 500


@app.route("/quote")
def quote():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol parameter is required"}), 400
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="1d", auto_adjust=True)

        if df is None or df.empty:
            return jsonify({"error": f"No data for {symbol}"}), 404

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        c  = float(last["Close"])
        pc = float(prev["Close"])

        return jsonify({
            "symbol":     symbol,
            "last_price": round(c, 2),
            "open":       round(float(last["Open"]), 2),
            "high":       round(float(last["High"]), 2),
            "low":        round(float(last["Low"]),  2),
            "prev_close": round(pc, 2),
            "change":     round(c - pc, 2),
            "change_pct": round(((c - pc) / pc) * 100, 2),
            "volume":     int(last["Volume"]) if pd.notna(last["Volume"]) else 0,
            "timestamp":  datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/multi")
def multi():
    symbols_raw = request.args.get("symbols", "").strip()
    interval    = request.args.get("interval", "1d").strip()
    if not symbols_raw:
        return jsonify({"error": "symbols parameter required"}), 400
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()][:30]
    iv_map = {"15m": "15m", "5m": "5m", "30m": "30m", "1h": "1h", "1d": "1d", "1wk": "1wk"}
    interval = iv_map.get(interval, interval)
    results = {}
    for symbol in symbols:
        try:
            df, used_iv = smart_fetch(symbol, interval)
            if df is None or df.empty:
                results[symbol] = {"error": "No data"}
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
            c  = float(last["Close"])
            pc = float(prev["Close"])
            candles_list = df_to_candles(df.tail(60), used_iv)
            results[symbol] = {
                "last_price": round(c, 2),
                "open":  round(float(last["Open"]), 2),
                "high":  round(float(last["High"]), 2),
                "low":   round(float(last["Low"]),  2),
                "prev_close": round(pc, 2),
                "change":     round(c - pc, 2),
                "change_pct": round(((c - pc) / pc) * 100, 2),
                "volume":     int(last["Volume"]) if pd.notna(last["Volume"]) else 0,
                "candles":    candles_list
            }
        except Exception as e:
            results[symbol] = {"error": str(e)}
    return jsonify({"interval": interval, "count": len(symbols), "data": results, "timestamp": datetime.utcnow().isoformat()})


@app.route("/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    DB = [
        {"symbol":"^NSEI",        "name":"Nifty 50 Index",           "exchange":"NSE", "type":"Index"},
        {"symbol":"^NSEBANK",     "name":"Bank Nifty Index",          "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXFINANCE",  "name":"Nifty Fin Services",        "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXIT",       "name":"Nifty IT Index",            "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXAUTO",     "name":"Nifty Auto Index",          "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXFMCG",     "name":"Nifty FMCG Index",          "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXPHARMA",   "name":"Nifty Pharma Index",        "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXMETAL",    "name":"Nifty Metal Index",         "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXREALTY",   "name":"Nifty Realty Index",        "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXENERGY",   "name":"Nifty Energy Index",        "exchange":"NSE", "type":"Index"},
        {"symbol":"^CNXPSUBANK",  "name":"Nifty PSU Bank Index",      "exchange":"NSE", "type":"Index"},
        {"symbol":"^INDIAVIX",    "name":"India VIX",                  "exchange":"NSE", "type":"Index"},
        {"symbol":"^BSESN",       "name":"BSE Sensex",                "exchange":"BSE", "type":"Index"},
        {"symbol":"^BSEMD",       "name":"BSE Midcap",                "exchange":"BSE", "type":"Index"},
        {"symbol":"^BSESML",      "name":"BSE Smallcap",              "exchange":"BSE", "type":"Index"},
        {"symbol":"^BANKEX",      "name":"BSE Bankex",                "exchange":"BSE", "type":"Index"},
        {"symbol":"RELIANCE.NS",  "name":"Reliance Industries",       "exchange":"NSE", "type":"Stock"},
        {"symbol":"TCS.NS",       "name":"Tata Consultancy Services", "exchange":"NSE", "type":"Stock"},
        {"symbol":"HDFCBANK.NS",  "name":"HDFC Bank",                 "exchange":"NSE", "type":"Stock"},
        {"symbol":"ICICIBANK.NS", "name":"ICICI Bank",                "exchange":"NSE", "type":"Stock"},
        {"symbol":"INFY.NS",      "name":"Infosys",                   "exchange":"NSE", "type":"Stock"},
        {"symbol":"SBIN.NS",      "name":"State Bank of India",       "exchange":"NSE", "type":"Stock"},
        {"symbol":"ITC.NS",       "name":"ITC Ltd",                   "exchange":"NSE", "type":"Stock"},
        {"symbol":"BHARTIARTL.NS","name":"Bharti Airtel",             "exchange":"NSE", "type":"Stock"},
        {"symbol":"LT.NS",        "name":"Larsen & Toubro",           "exchange":"NSE", "type":"Stock"},
        {"symbol":"HCLTECH.NS",   "name":"HCL Technologies",          "exchange":"NSE", "type":"Stock"},
        {"symbol":"WIPRO.NS",     "name":"Wipro",                     "exchange":"NSE", "type":"Stock"},
        {"symbol":"KOTAKBANK.NS", "name":"Kotak Mahindra Bank",       "exchange":"NSE", "type":"Stock"},
        {"symbol":"HINDUNILVR.NS","name":"Hindustan Unilever",        "exchange":"NSE", "type":"Stock"},
        {"symbol":"BAJFINANCE.NS","name":"Bajaj Finance",             "exchange":"NSE", "type":"Stock"},
        {"symbol":"AXISBANK.NS",  "name":"Axis Bank",                 "exchange":"NSE", "type":"Stock"},
        {"symbol":"MARUTI.NS",    "name":"Maruti Suzuki",             "exchange":"NSE", "type":"Stock"},
        {"symbol":"SUNPHARMA.NS", "name":"Sun Pharma",                "exchange":"NSE", "type":"Stock"},
        {"symbol":"TITAN.NS",     "name":"Titan Company",             "exchange":"NSE", "type":"Stock"},
        {"symbol":"NTPC.NS",      "name":"NTPC",                      "exchange":"NSE", "type":"Stock"},
        {"symbol":"TATAMOTORS.NS","name":"Tata Motors",               "exchange":"NSE", "type":"Stock"},
        {"symbol":"TATASTEEL.NS", "name":"Tata Steel",                "exchange":"NSE", "type":"Stock"},
        {"symbol":"ONGC.NS",      "name":"ONGC",                      "exchange":"NSE", "type":"Stock"},
        {"symbol":"JSWSTEEL.NS",  "name":"JSW Steel",                 "exchange":"NSE", "type":"Stock"},
        {"symbol":"POWERGRID.NS", "name":"Power Grid Corporation",    "exchange":"NSE", "type":"Stock"},
        {"symbol":"HINDALCO.NS",  "name":"Hindalco Industries",       "exchange":"NSE", "type":"Stock"},
        {"symbol":"ADANIENT.NS",  "name":"Adani Enterprises",         "exchange":"NSE", "type":"Stock"},
        {"symbol":"ZOMATO.NS",    "name":"Zomato",                    "exchange":"NSE", "type":"Stock"},
        {"symbol":"IRCTC.NS",     "name":"IRCTC",                     "exchange":"NSE", "type":"Stock"},
        {"symbol":"TATAPOWER.NS", "name":"Tata Power",                "exchange":"NSE", "type":"Stock"},
        {"symbol":"INDUSINDBK.NS","name":"IndusInd Bank",             "exchange":"NSE", "type":"Stock"},
        {"symbol":"PNB.NS",       "name":"Punjab National Bank",      "exchange":"NSE", "type":"Stock"},
        {"symbol":"BANKBARODA.NS","name":"Bank of Baroda",            "exchange":"NSE", "type":"Stock"},
        {"symbol":"CANBK.NS",     "name":"Canara Bank",               "exchange":"NSE", "type":"Stock"},
        {"symbol":"IDFCFIRSTB.NS","name":"IDFC First Bank",           "exchange":"NSE", "type":"Stock"},
        {"symbol":"NIFTYBEES.NS", "name":"Nifty 50 BeES ETF",         "exchange":"NSE", "type":"ETF"},
        {"symbol":"BANKBEES.NS",  "name":"Bank Nifty BeES ETF",       "exchange":"NSE", "type":"ETF"},
        {"symbol":"GOLDBEES.NS",  "name":"Gold BeES ETF",             "exchange":"NSE", "type":"ETF"},
        {"symbol":"GC=F",         "name":"Gold Futures (COMEX)",      "exchange":"COMEX","type":"Commodity"},
        {"symbol":"CL=F",         "name":"WTI Crude Oil Futures",     "exchange":"NYMEX","type":"Commodity"},
        {"symbol":"SI=F",         "name":"Silver Futures",            "exchange":"COMEX","type":"Commodity"},
        {"symbol":"^GSPC",        "name":"S&P 500 Index",             "exchange":"NYSE", "type":"Index"},
        {"symbol":"^IXIC",        "name":"Nasdaq Composite",          "exchange":"NASDAQ","type":"Index"},
        {"symbol":"^N225",        "name":"Nikkei 225 Japan",          "exchange":"TSE",  "type":"Index"},
        {"symbol":"BTC-USD",      "name":"Bitcoin USD",               "exchange":"Crypto","type":"Crypto"},
        {"symbol":"ETH-USD",      "name":"Ethereum USD",              "exchange":"Crypto","type":"Crypto"},
        {"symbol":"INR=X",        "name":"USD / Indian Rupee",        "exchange":"Forex", "type":"Forex"},
    ]

    results = [s for s in DB if q in s["symbol"].lower() or q in s["name"].lower()][:15]
    return jsonify({"query": q, "count": len(results), "results": results})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)

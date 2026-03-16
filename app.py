"""
SignalForge Backend — Free deployment on Render.com
Fetches NSE/BSE/Commodity/Global data from Yahoo Finance server-side.
No CORS issues. No API key. Fully free.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime
import traceback

app = Flask(__name__)

# Allow requests from any origin (your Claude widget, your HTML file, anywhere)
CORS(app, origins="*")

# ── Interval → yfinance period mapping ──────────────────────────────────────
INTERVAL_PERIOD = {
    "5m":  "5d",
    "15m": "5d",
    "30m": "5d",
    "1h":  "1mo",
    "1d":  "6mo",
    "1wk": "2y",
}

@app.route("/")
def index():
    return jsonify({
        "service": "SignalForge Data API",
        "version": "1.0",
        "status":  "running",
        "endpoints": {
            "candles":  "/candles?symbol=RELIANCE.NS&interval=1d",
            "quote":    "/quote?symbol=^NSEI",
            "multi":    "/multi?symbols=^NSEI,^NSEBANK,RELIANCE.NS&interval=1d",
            "search":   "/search?q=reliance",
            "health":   "/health"
        },
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@app.route("/candles")
def candles():
    """
    Get OHLCV candle data for a single symbol.
    Query params:
      symbol   - Yahoo Finance ticker  e.g. RELIANCE.NS, ^NSEI, BTC-USD
      interval - 5m | 15m | 30m | 1h | 1d | 1wk  (default: 1d)
      period   - override auto period  e.g. 3mo, 6mo, 1y, 2y
    """
    symbol   = request.args.get("symbol", "").strip()
    interval = request.args.get("interval", "1d").strip()
    period   = request.args.get("period", "").strip()

    if not symbol:
        return jsonify({"error": "symbol parameter is required"}), 400

    if interval not in INTERVAL_PERIOD:
        return jsonify({"error": f"interval must be one of: {', '.join(INTERVAL_PERIOD)}"}), 400

    if not period:
        period = INTERVAL_PERIOD[interval]

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)

        if df is None or df.empty:
            return jsonify({"error": f"No data returned for {symbol}. Market may be closed or symbol invalid."}), 404

        # Build clean candle list
        candles_list = []
        for ts, row in df.iterrows():
            # Format datetime sensibly
            if hasattr(ts, 'strftime'):
                if interval in ("1d", "1wk"):
                    dt_str = ts.strftime("%Y-%m-%d")
                else:
                    # Convert to IST (UTC+5:30)
                    ist = ts.tz_convert("Asia/Kolkata") if ts.tzinfo else ts
                    dt_str = ist.strftime("%Y-%m-%d %H:%M")
            else:
                dt_str = str(ts)[:16]

            o = round(float(row["Open"]),  4) if pd.notna(row["Open"])  else None
            h = round(float(row["High"]),  4) if pd.notna(row["High"])  else None
            l = round(float(row["Low"]),   4) if pd.notna(row["Low"])   else None
            c = round(float(row["Close"]), 4) if pd.notna(row["Close"]) else None
            v = int(row["Volume"])             if pd.notna(row["Volume"]) else 0

            # Skip bad candles
            if c is None or c <= 0 or o is None:
                continue

            candles_list.append({"dt": dt_str, "o": o, "h": h, "l": l, "c": c, "v": v})

        if not candles_list:
            return jsonify({"error": "All candles were null or zero. Try a different interval or period."}), 404

        # Return last 100 candles max
        candles_list = candles_list[-100:]

        return jsonify({
            "symbol":   symbol,
            "interval": interval,
            "period":   period,
            "count":    len(candles_list),
            "candles":  candles_list
        })

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


@app.route("/quote")
def quote():
    """
    Get latest quote for a symbol.
    Query params:
      symbol - Yahoo Finance ticker
    """
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol parameter is required"}), 400

    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.fast_info

        # Get last 2 daily candles for change calculation
        df = ticker.history(period="5d", interval="1d", auto_adjust=True)

        quote_data = {
            "symbol":        symbol,
            "last_price":    None,
            "open":          None,
            "high":          None,
            "low":           None,
            "prev_close":    None,
            "change":        None,
            "change_pct":    None,
            "volume":        None,
            "timestamp":     datetime.utcnow().isoformat()
        }

        if df is not None and not df.empty:
            last  = df.iloc[-1]
            prev  = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
            c     = float(last["Close"])
            pc    = float(prev["Close"])
            quote_data.update({
                "last_price": round(c, 2),
                "open":       round(float(last["Open"]),  2),
                "high":       round(float(last["High"]),  2),
                "low":        round(float(last["Low"]),   2),
                "prev_close": round(pc, 2),
                "change":     round(c - pc, 2),
                "change_pct": round(((c - pc) / pc) * 100, 2),
                "volume":     int(last["Volume"]) if pd.notna(last["Volume"]) else 0
            })

        return jsonify(quote_data)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/multi")
def multi():
    """
    Get latest quotes for multiple symbols in one call.
    Query params:
      symbols  - comma-separated Yahoo Finance tickers
      interval - 5m | 15m | 30m | 1h | 1d | 1wk  (default: 1d)
    """
    symbols_raw = request.args.get("symbols", "").strip()
    interval    = request.args.get("interval", "1d").strip()

    if not symbols_raw:
        return jsonify({"error": "symbols parameter is required"}), 400

    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "No valid symbols provided"}), 400
    if len(symbols) > 30:
        return jsonify({"error": "Maximum 30 symbols per request"}), 400

    if interval not in INTERVAL_PERIOD:
        return jsonify({"error": f"interval must be one of: {', '.join(INTERVAL_PERIOD)}"}), 400

    period = INTERVAL_PERIOD[interval]
    results = {}

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval, auto_adjust=True)

            if df is None or df.empty:
                results[symbol] = {"error": "No data"}
                continue

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
            c  = float(last["Close"])
            pc = float(prev["Close"])

            # Build last 60 candles for signal calculation
            candles_list = []
            for ts, row in df.tail(60).iterrows():
                if hasattr(ts, 'strftime'):
                    dt_str = ts.strftime("%Y-%m-%d") if interval in ("1d","1wk") else ts.strftime("%Y-%m-%d %H:%M")
                else:
                    dt_str = str(ts)[:16]
                cv = round(float(row["Close"]), 4) if pd.notna(row["Close"]) else None
                ov = round(float(row["Open"]),  4) if pd.notna(row["Open"])  else None
                if cv is None or cv <= 0 or ov is None:
                    continue
                candles_list.append({
                    "dt": dt_str,
                    "o": ov,
                    "h": round(float(row["High"]), 4),
                    "l": round(float(row["Low"]),  4),
                    "c": cv,
                    "v": int(row["Volume"]) if pd.notna(row["Volume"]) else 0
                })

            results[symbol] = {
                "last_price": round(c, 2),
                "open":       round(float(last["Open"]), 2),
                "high":       round(float(last["High"]), 2),
                "low":        round(float(last["Low"]),  2),
                "prev_close": round(pc, 2),
                "change":     round(c - pc, 2),
                "change_pct": round(((c - pc) / pc) * 100, 2),
                "volume":     int(last["Volume"]) if pd.notna(last["Volume"]) else 0,
                "candles":    candles_list
            }

        except Exception as e:
            results[symbol] = {"error": str(e)}

    return jsonify({
        "interval": interval,
        "count":    len(symbols),
        "data":     results,
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/search")
def search():
    """
    Search for symbols. Basic keyword match against a curated Indian market list.
    Query params:
      q - search query (company name or ticker)
    """
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"error": "q parameter is required"}), 400

    SYMBOL_DB = [
        # NSE Indices
        {"symbol":"^NSEI",        "name":"Nifty 50 Index",          "exchange":"NSE",   "type":"Index"},
        {"symbol":"^NSEBANK",     "name":"Bank Nifty Index",         "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXFINANCE",  "name":"Nifty Fin Services",       "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXIT",       "name":"Nifty IT Index",           "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXAUTO",     "name":"Nifty Auto Index",         "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXFMCG",     "name":"Nifty FMCG Index",         "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXPHARMA",   "name":"Nifty Pharma Index",       "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXMETAL",    "name":"Nifty Metal Index",        "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXREALTY",   "name":"Nifty Realty Index",       "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXENERGY",   "name":"Nifty Energy Index",       "exchange":"NSE",   "type":"Index"},
        {"symbol":"^CNXPSUBANK",  "name":"Nifty PSU Bank Index",     "exchange":"NSE",   "type":"Index"},
        {"symbol":"^INDIAVIX",    "name":"India VIX",                "exchange":"NSE",   "type":"Index"},
        # BSE Indices
        {"symbol":"^BSESN",       "name":"BSE Sensex",               "exchange":"BSE",   "type":"Index"},
        {"symbol":"^BSEMD",       "name":"BSE Midcap",               "exchange":"BSE",   "type":"Index"},
        {"symbol":"^BSESML",      "name":"BSE Smallcap",             "exchange":"BSE",   "type":"Index"},
        {"symbol":"^BANKEX",      "name":"BSE Bankex",               "exchange":"BSE",   "type":"Index"},
        # NSE Stocks
        {"symbol":"RELIANCE.NS",  "name":"Reliance Industries",      "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TCS.NS",       "name":"Tata Consultancy Services","exchange":"NSE",   "type":"Stock"},
        {"symbol":"HDFCBANK.NS",  "name":"HDFC Bank",                "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ICICIBANK.NS", "name":"ICICI Bank",               "exchange":"NSE",   "type":"Stock"},
        {"symbol":"INFY.NS",      "name":"Infosys",                  "exchange":"NSE",   "type":"Stock"},
        {"symbol":"SBIN.NS",      "name":"State Bank of India",      "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ITC.NS",       "name":"ITC Ltd",                  "exchange":"NSE",   "type":"Stock"},
        {"symbol":"BHARTIARTL.NS","name":"Bharti Airtel",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"LT.NS",        "name":"Larsen & Toubro",          "exchange":"NSE",   "type":"Stock"},
        {"symbol":"HCLTECH.NS",   "name":"HCL Technologies",         "exchange":"NSE",   "type":"Stock"},
        {"symbol":"WIPRO.NS",     "name":"Wipro",                    "exchange":"NSE",   "type":"Stock"},
        {"symbol":"KOTAKBANK.NS", "name":"Kotak Mahindra Bank",      "exchange":"NSE",   "type":"Stock"},
        {"symbol":"HINDUNILVR.NS","name":"Hindustan Unilever",       "exchange":"NSE",   "type":"Stock"},
        {"symbol":"BAJFINANCE.NS","name":"Bajaj Finance",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"AXISBANK.NS",  "name":"Axis Bank",                "exchange":"NSE",   "type":"Stock"},
        {"symbol":"MARUTI.NS",    "name":"Maruti Suzuki",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"SUNPHARMA.NS", "name":"Sun Pharma",               "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TITAN.NS",     "name":"Titan Company",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"NTPC.NS",      "name":"NTPC",                     "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TATAMOTORS.NS","name":"Tata Motors",              "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TATASTEEL.NS", "name":"Tata Steel",               "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ONGC.NS",      "name":"ONGC",                     "exchange":"NSE",   "type":"Stock"},
        {"symbol":"JSWSTEEL.NS",  "name":"JSW Steel",                "exchange":"NSE",   "type":"Stock"},
        {"symbol":"POWERGRID.NS", "name":"Power Grid Corporation",   "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TECHM.NS",     "name":"Tech Mahindra",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ADANIENT.NS",  "name":"Adani Enterprises",        "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ADANIPORTS.NS","name":"Adani Ports",              "exchange":"NSE",   "type":"Stock"},
        {"symbol":"HINDALCO.NS",  "name":"Hindalco Industries",      "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ULTRACEMCO.NS","name":"UltraTech Cement",         "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ASIANPAINT.NS","name":"Asian Paints",             "exchange":"NSE",   "type":"Stock"},
        {"symbol":"NESTLEIND.NS", "name":"Nestle India",             "exchange":"NSE",   "type":"Stock"},
        {"symbol":"BAJAJFINSV.NS","name":"Bajaj Finserv",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"INDUSINDBK.NS","name":"IndusInd Bank",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"BANDHANBNK.NS","name":"Bandhan Bank",             "exchange":"NSE",   "type":"Stock"},
        {"symbol":"FEDERALBNK.NS","name":"Federal Bank",             "exchange":"NSE",   "type":"Stock"},
        {"symbol":"IDFCFIRSTB.NS","name":"IDFC First Bank",          "exchange":"NSE",   "type":"Stock"},
        {"symbol":"PNB.NS",       "name":"Punjab National Bank",     "exchange":"NSE",   "type":"Stock"},
        {"symbol":"BANKBARODA.NS","name":"Bank of Baroda",           "exchange":"NSE",   "type":"Stock"},
        {"symbol":"CANBK.NS",     "name":"Canara Bank",              "exchange":"NSE",   "type":"Stock"},
        {"symbol":"ZOMATO.NS",    "name":"Zomato",                   "exchange":"NSE",   "type":"Stock"},
        {"symbol":"IRCTC.NS",     "name":"IRCTC",                    "exchange":"NSE",   "type":"Stock"},
        {"symbol":"TATAPOWER.NS", "name":"Tata Power",               "exchange":"NSE",   "type":"Stock"},
        {"symbol":"HAVELLS.NS",   "name":"Havells India",            "exchange":"NSE",   "type":"Stock"},
        {"symbol":"MUTHOOTFIN.NS","name":"Muthoot Finance",          "exchange":"NSE",   "type":"Stock"},
        {"symbol":"DMART.NS",     "name":"Avenue Supermarts (DMart)","exchange":"NSE",   "type":"Stock"},
        {"symbol":"NYKAA.NS",     "name":"FSN E-Commerce (Nykaa)",   "exchange":"NSE",   "type":"Stock"},
        {"symbol":"PAYTM.NS",     "name":"One97 Communications",     "exchange":"NSE",   "type":"Stock"},
        # ETFs
        {"symbol":"NIFTYBEES.NS", "name":"Nifty 50 BeES ETF",        "exchange":"NSE",   "type":"ETF"},
        {"symbol":"BANKBEES.NS",  "name":"Bank Nifty BeES ETF",      "exchange":"NSE",   "type":"ETF"},
        {"symbol":"GOLDBEES.NS",  "name":"Gold BeES ETF",            "exchange":"NSE",   "type":"ETF"},
        {"symbol":"ITBEES.NS",    "name":"Nifty IT BeES ETF",        "exchange":"NSE",   "type":"ETF"},
        # Commodities
        {"symbol":"GC=F",         "name":"Gold Futures (COMEX)",     "exchange":"COMEX", "type":"Commodity"},
        {"symbol":"CL=F",         "name":"WTI Crude Oil Futures",    "exchange":"NYMEX", "type":"Commodity"},
        {"symbol":"SI=F",         "name":"Silver Futures",           "exchange":"COMEX", "type":"Commodity"},
        {"symbol":"XAU=X",        "name":"Gold Spot USD",            "exchange":"Forex",  "type":"Forex"},
        # Global
        {"symbol":"^GSPC",        "name":"S&P 500 Index",            "exchange":"NYSE",   "type":"Index"},
        {"symbol":"^IXIC",        "name":"Nasdaq Composite",         "exchange":"NASDAQ", "type":"Index"},
        {"symbol":"^N225",        "name":"Nikkei 225 Japan",         "exchange":"TSE",    "type":"Index"},
        {"symbol":"^GDAXI",       "name":"DAX Germany",              "exchange":"XETRA",  "type":"Index"},
        {"symbol":"^FTSE",        "name":"FTSE 100 UK",              "exchange":"LSE",    "type":"Index"},
        {"symbol":"BTC-USD",      "name":"Bitcoin USD",              "exchange":"Crypto", "type":"Crypto"},
        {"symbol":"ETH-USD",      "name":"Ethereum USD",             "exchange":"Crypto", "type":"Crypto"},
        {"symbol":"INR=X",        "name":"USD / Indian Rupee",       "exchange":"Forex",  "type":"Forex"},
        {"symbol":"EURUSD=X",     "name":"Euro / US Dollar",         "exchange":"Forex",  "type":"Forex"},
    ]

    results = [
        s for s in SYMBOL_DB
        if q in s["symbol"].lower() or q in s["name"].lower()
    ][:15]

    return jsonify({"query": q, "count": len(results), "results": results})


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)

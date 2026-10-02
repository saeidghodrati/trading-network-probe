import json
import math
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.wallex.ir"
BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB = DATA / "paper.db"
LOG = DATA / "monitor.jsonl"
TOP_N = int(os.getenv("TOP_N", "100"))
INTERVAL = int(os.getenv("INTERVAL_SECONDS", "300"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "120"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_json(path, params=None, timeout=15):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "wallex-paper-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def db_conn():
    DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS scans(
        ts TEXT, symbol TEXT, price REAL, quote_volume REAL,
        change24 REAL, ema20 REAL, ema50 REAL, rsi14 REAL, signal TEXT
    )""")
    con.commit()
    return con

def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    out = sum(values[:period]) / period
    for v in values[period:]:
        out = alpha * v + (1 - alpha) * out
    return out

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for a, b in zip(values[:-1], values[1:]):
        d = b - a
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def markets():
    payload = get_json("/v1/markets")
    symbols = payload.get("result", {}).get("symbols", {})
    rows = []
    for symbol, item in symbols.items():
        if not symbol.endswith("USDT"):
            continue
        stats = item.get("stats", {}) or {}
        try:
            rows.append({
                "symbol": symbol,
                "price": float(stats.get("lastPrice") or 0),
                "quote_volume": float(stats.get("24h_quoteVolume") or 0),
                "change24": float(stats.get("24h_ch") or 0),
            })
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x["quote_volume"], reverse=True)
    return rows[:TOP_N]

def history(symbol):
    end = int(time.time())
    start = end - LOOKBACK_HOURS * 3600
    payload = get_json("/v1/udf/history", {
        "symbol": symbol,
        "resolution": "60",
        "from": start,
        "to": end,
    })
    closes = [float(x) for x in payload.get("c", [])]
    return closes

def analyze(row):
    closes = history(row["symbol"])
    if len(closes) < 55:
        return None
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    r14 = rsi(closes, 14)
    signal = "HOLD"
    if e20 and e50 and r14 is not None:
        if e20 > e50 and 50 <= r14 <= 68 and row["change24"] > 0:
            signal = "WATCH_BUY"
        elif e20 < e50 or r14 >= 74:
            signal = "WATCH_SELL"
    return {
        **row,
        "ema20": e20,
        "ema50": e50,
        "rsi14": r14,
        "signal": signal,
    }

def run_cycle():
    started = time.time()
    rows = markets()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze, row): row for row in rows}
        for f in as_completed(futures):
            try:
                item = f.result()
                if item:
                    results.append(item)
            except Exception as exc:
                print(json.dumps({"event": "symbol_error", "symbol": futures[f]["symbol"], "error": str(exc)}), flush=True)

    ts = now_iso()
    con = db_conn()
    for item in results:
        con.execute(
            "INSERT INTO scans VALUES(?,?,?,?,?,?,?,?,?)",
            (
                ts, item["symbol"], item["price"], item["quote_volume"],
                item["change24"], item["ema20"], item["ema50"],
                item["rsi14"], item["signal"]
            ),
        )
    con.commit()
    con.close()

    summary = {
        "event": "scan_complete",
        "time": ts,
        "markets_scanned": len(results),
        "watch_buy": [x["symbol"] for x in results if x["signal"] == "WATCH_BUY"],
        "watch_sell": [x["symbol"] for x in results if x["signal"] == "WATCH_SELL"],
        "elapsed_sec": round(time.time() - started, 2),
        "mode": "paper-monitor-only",
    }
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "event": "started",
        "time": now_iso(),
        "top_n": TOP_N,
        "interval_seconds": INTERVAL,
        "mode": "paper-monitor-only",
        "real_orders": False,
    }), flush=True)
    while True:
        try:
            run_cycle()
        except Exception as exc:
            print(json.dumps({"event": "cycle_error", "error": str(exc)}), flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()

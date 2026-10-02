import sqlite3
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "paper.db"

START_BALANCE = 10000.0
MAX_POSITIONS = 5
POSITION_FRACTION = 0.10
STOP_LOSS = 0.03
TAKE_PROFIT = 0.06

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS account(
        id INTEGER PRIMARY KEY CHECK(id=1),
        cash REAL NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS positions(
        symbol TEXT PRIMARY KEY,
        qty REAL NOT NULL,
        entry REAL NOT NULL,
        opened_ts INTEGER NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        price REAL NOT NULL,
        qty REAL NOT NULL,
        pnl REAL NOT NULL DEFAULT 0
    )""")
    con.execute("INSERT OR IGNORE INTO account(id,cash) VALUES(1,?)", (START_BALANCE,))
    con.commit()
    return con

def latest_signals(con):
    row = con.execute("SELECT MAX(ts) FROM scans").fetchone()
    if not row or not row[0]:
        return []
    return con.execute(
        "SELECT symbol,price,signal FROM scans WHERE ts=?",
        (row[0],)
    ).fetchall()

def run_once():
    con = conn()
    signals = latest_signals(con)
    if not signals:
        con.close()
        return

    positions = {
        r[0]: {"qty": r[1], "entry": r[2]}
        for r in con.execute("SELECT symbol,qty,entry FROM positions")
    }
    cash = con.execute("SELECT cash FROM account WHERE id=1").fetchone()[0]

    prices = {s: p for s, p, _ in signals if p and p > 0}
    signal_map = {s: sig for s, _, sig in signals}

    for symbol, pos in list(positions.items()):
        price = prices.get(symbol)
        if not price:
            continue
        change = (price / pos["entry"]) - 1
        should_exit = (
            signal_map.get(symbol) == "WATCH_SELL"
            or change <= -STOP_LOSS
            or change >= TAKE_PROFIT
        )
        if should_exit:
            proceeds = pos["qty"] * price
            pnl = pos["qty"] * (price - pos["entry"])
            cash += proceeds
            con.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            con.execute(
                "INSERT INTO trades(ts,symbol,side,price,qty,pnl) VALUES(?,?,?,?,?,?)",
                (int(time.time()), symbol, "SELL", price, pos["qty"], pnl)
            )
            del positions[symbol]

    slots = max(0, MAX_POSITIONS - len(positions))
    if slots:
        equity = cash + sum(
            p["qty"] * prices.get(sym, p["entry"])
            for sym, p in positions.items()
        )
        budget = equity * POSITION_FRACTION
        buys = [
            (s, p) for s, p, sig in signals
            if sig == "WATCH_BUY" and s not in positions and p and p > 0
        ][:slots]
        for symbol, price in buys:
            spend = min(budget, cash)
            if spend <= 0:
                break
            qty = spend / price
            cash -= spend
            con.execute(
                "INSERT INTO positions(symbol,qty,entry,opened_ts) VALUES(?,?,?,?)",
                (symbol, qty, price, int(time.time()))
            )
            con.execute(
                "INSERT INTO trades(ts,symbol,side,price,qty,pnl) VALUES(?,?,?,?,?,0)",
                (int(time.time()), symbol, "BUY", price, qty)
            )
            positions[symbol] = {"qty": qty, "entry": price}

    con.execute("UPDATE account SET cash=? WHERE id=1", (cash,))
    con.commit()
    con.close()

if __name__ == "__main__":
    run_once()

import sqlite3

db = "data/paper.db"
con = sqlite3.connect(db)

cash = con.execute(
    "SELECT cash FROM account WHERE id=1"
).fetchone()[0]

positions = con.execute("""
SELECT p.symbol, p.qty, p.entry,
       (
         SELECT s.price
         FROM scans s
         WHERE s.symbol = p.symbol
         ORDER BY s.ts DESC
         LIMIT 1
       )
FROM positions p
""").fetchall()

realized = con.execute(
    "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE side='SELL'"
).fetchone()[0]

market_value = 0
unrealized = 0

print("\nPOSITIONS\n")

for symbol, qty, entry, current in positions:
    if current is None:
        continue
    cost = qty * entry
    value = qty * current
    pnl = value - cost
    pct = (current / entry - 1) * 100
    market_value += value
    unrealized += pnl
    print(
        f"{symbol:12} "
        f"entry={entry:.8f} "
        f"now={current:.8f} "
        f"PnL={pnl:.2f} USDT "
        f"({pct:.2f}%)"
    )

equity = cash + market_value

print("\nSUMMARY")
print(f"Cash:           {cash:.2f} USDT")
print(f"Market Value:   {market_value:.2f} USDT")
print(f"Unrealized PnL: {unrealized:.2f} USDT")
print(f"Realized PnL:   {realized:.2f} USDT")
print(f"Equity:         {equity:.2f} USDT")

con.close()

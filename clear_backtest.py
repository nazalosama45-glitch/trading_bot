import os
import sqlite3

from bot import learner

learner.init_db()
con = sqlite3.connect("data/trades.db")
n = con.execute("DELETE FROM trades WHERE source = 'backtest'").rowcount
con.commit()
con.close()
print("cleared old backtest rows:", n)

if os.path.exists("models/model.pkl"):
    os.remove("models/model.pkl")
    print("removed old model")

"""
Learning layer: logs every trade's features + outcome to SQLite,
retrains a classifier every RETRAIN_EVERY trades, and persists the model.
"""
import sqlite3
import pickle
import logging
import json
import os
from pathlib import Path
from bot import config

logger = logging.getLogger(__name__)

DB_PATH = Path("data/trades.db")
MODEL_PATH = Path("models/model.pkl")


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                symbol TEXT,
                side TEXT,
                entry REAL,
                exit_price REAL,
                pnl REAL,
                profitable INTEGER,
                features TEXT,
                source TEXT DEFAULT 'live'
            )
        """)
        cols = [r[1] for r in con.execute("PRAGMA table_info(trades)").fetchall()]
        if "pnl_usd" not in cols:
            con.execute("ALTER TABLE trades ADD COLUMN pnl_usd REAL DEFAULT 0")
        if "source" not in cols:
            # Rows created before this column existed all came from backtests
            con.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'backtest'")
        con.commit()


def log_trade(ts: str, symbol: str, side: str, entry: float,
              exit_price: float, pnl: float, features: list, pnl_usd: float = 0.0):
    profitable = 1 if pnl > 0 else 0
    with _conn() as con:
        con.execute(
            "INSERT INTO trades (ts, symbol, side, entry, exit_price, pnl, profitable, features, source, pnl_usd) "
            "VALUES (?,?,?,?,?,?,?,?,'live',?)",
            (ts, symbol, side, entry, exit_price, pnl, profitable, json.dumps(features), pnl_usd)
        )
        con.commit()
    logger.info(f"Trade logged: {symbol} {side} pnl={pnl:.4f} profitable={bool(profitable)}")


def _load_training_data():
    with _conn() as con:
        rows = con.execute(
            "SELECT features, profitable FROM trades WHERE exit_price IS NOT NULL AND source = 'live'"
        ).fetchall()
        if len(rows) < 100:
            # Not enough of the bot's own trades yet: fall back to history + live together
            rows = con.execute(
                "SELECT features, profitable FROM trades WHERE exit_price IS NOT NULL"
            ).fetchall()
    if len(rows) < 20:
        return None, None
    X, y = [], []
    for features_json, profitable in rows:
        features = json.loads(features_json)
        if len(features) == 7:
            X.append(features)
            y.append(profitable)
    if len(X) < 20:
        return None, None
    return X, y


def retrain() -> object | None:
    """Train a GradientBoosting classifier on trade history. Returns model or None."""
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline

        X, y = _load_training_data()
        if X is None:
            logger.info("Not enough trades yet to train ML model.")
            return None

        pos = sum(y)
        neg = len(y) - pos
        logger.info(f"Training on {len(X)} trades ({pos} wins / {neg} losses)")

        model = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.05,
                max_depth=3,
                random_state=42,
            )),
        ])
        model.fit(X, y)

        MODEL_PATH.parent.mkdir(exist_ok=True)
        # Safe: model is trained and loaded by this process only, never from external input
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(model, f)

        logger.info(f"ML model saved to {MODEL_PATH}")
        return model
    except Exception as e:
        logger.error(f"Retrain failed: {e}")
        return None


def load_model() -> object | None:
    if MODEL_PATH.exists():
        try:
            # Safe: file is written only by this process's retrain()
            with open(MODEL_PATH, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning(f"Could not load model: {e}")
    return None


def bulk_insert_trades(trades: list) -> int:
    """Insert backtest trades marked as source='backtest' (used for ML training only)."""
    rows = [
        (t.ts, t.symbol, t.side, t.entry, t.exit_price, t.pnl, t.profitable, json.dumps(t.features), 'backtest')
        for t in trades
    ]
    with _conn() as con:
        con.executemany(
            "INSERT INTO trades (ts, symbol, side, entry, exit_price, pnl, profitable, features, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
    logger.info(f"Inserted {len(rows)} backtest trades into DB.")
    return len(rows)


def live_trade_count() -> int:
    try:
        with _conn() as con:
            return con.execute("SELECT COUNT(*) FROM trades WHERE source = 'live'").fetchone()[0]
    except Exception:
        return 0


def trade_count() -> int:
    try:
        with _conn() as con:
            return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    except Exception:
        return 0

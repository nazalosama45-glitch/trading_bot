"""
Learning layer. Every finished trade (real, shadow or historical) is stored with the market
conditions at entry and whether it won. The model is retrained on all of them, tested on the
newest 25% it has not seen, and that test picks how confident it must be before a real trade.
"""
import csv
import json
import logging
import pickle
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bot import config

logger = logging.getLogger(__name__)

DB_PATH = Path("data/trades.db")
MODEL_PATH = Path("models/model.pkl")
LEARNING_PATH = Path("models/learning.json")
SEED_PATH = Path(__file__).parent.parent / "seed" / "backtest_trades.csv"

THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
NO_EDGE_THRESHOLD = 0.99  # nothing tested beat the market, so the model approves almost nothing


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


def log_shadow(result: dict):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as con:
        con.execute(
            "INSERT INTO trades (ts, symbol, side, entry, exit_price, pnl, profitable, features, source, pnl_usd) "
            "VALUES (?,?,?,?,?,?,?,?,'shadow',0)",
            (ts, result["symbol"], result.get("side", "buy"), result["entry"], result["exit"],
             result["pnl_pct"] * result["entry"], result["profitable"], json.dumps(result["features"]))
        )
        con.commit()


def with_side(features: list, side: str) -> list:
    """Model input = the 10 market readings plus which direction is being bet on."""
    return list(features) + [1.0 if side == "buy" else 0.0]


def labeled_count() -> int:
    try:
        with _conn() as con:
            return con.execute("SELECT COUNT(*) FROM trades WHERE exit_price IS NOT NULL").fetchone()[0]
    except Exception:
        return 0


def source_counts() -> dict:
    try:
        with _conn() as con:
            rows = con.execute(
                "SELECT source, COUNT(*) FROM trades WHERE exit_price IS NOT NULL GROUP BY source"
            ).fetchall()
        return {name: n for name, n in rows}
    except Exception:
        return {}


def _sort_key(ts: str) -> str:
    return (ts or "").replace("T", " ")[:19]


def _load_rows() -> list:
    """(ts, features, won, return) for every labeled trade whose features match the current format."""
    with _conn() as con:
        raw = con.execute(
            "SELECT ts, features, profitable, pnl, entry, side FROM trades WHERE exit_price IS NOT NULL"
        ).fetchall()
    rows = []
    for ts, features_json, won, pnl, entry, side in raw:
        try:
            features = json.loads(features_json)
        except (TypeError, ValueError):
            continue
        if len(features) != config.FEATURE_LEN or not entry:
            continue
        ret = float(pnl) / float(entry)
        if side == "sell":
            ret = abs(ret) if won else -abs(ret)   # stored pnl is already direction-adjusted
        rows.append((_sort_key(ts), with_side(features, side or "buy"), int(won), ret))
    rows.sort(key=lambda r: r[0])
    return rows


def _stats(returns: list) -> dict:
    n = len(returns)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "profit_factor": 0.0, "avg_ret": 0.0}
    gain = sum(r for r in returns if r > 0)
    loss = -sum(r for r in returns if r <= 0)
    return {
        "n": n,
        "win_rate": sum(1 for r in returns if r > 0) / n,
        "profit_factor": min(gain / loss, 99.0) if loss > 0 else (99.0 if gain > 0 else 0.0),
        "avg_ret": sum(returns) / n,
    }


def retrain():
    """Train on every labeled example. Returns (model, threshold) or None if there is too little data."""
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier

        rows = _load_rows()
        if len(rows) < 100:
            logger.info(f"Only {len(rows)} labeled examples so far; need 100 to train.")
            return None

        X = [r[1] for r in rows]
        y = [r[2] for r in rows]
        rets = [r[3] for r in rows]

        def make():
            return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, random_state=42)

        report = {"trained_at": datetime.now(timezone.utc).isoformat(), "rows": len(rows),
                  "sources": source_counts(), "holdout": [], "baseline": None, "edge_found": False}
        threshold = None

        if len(rows) >= 300:
            split = int(len(rows) * 0.75)
            probs = make().fit(X[:split], y[:split]).predict_proba(X[split:])[:, 1]
            test_rets = rets[split:]
            report["baseline"] = _stats(test_rets)
            for t in THRESHOLDS:
                s = _stats([r for r, p in zip(test_rets, probs) if p >= t])
                s["threshold"] = t
                report["holdout"].append(s)
                if threshold is None and s["n"] >= 30 and s["profit_factor"] >= 1.1 and s["avg_ret"] > 0:
                    threshold = t
        report["edge_found"] = threshold is not None
        report["threshold"] = threshold if threshold is not None else NO_EDGE_THRESHOLD

        model = make().fit(X, y)
        MODEL_PATH.parent.mkdir(exist_ok=True)
        # Safe: the model is trained and read back by this app only, never taken from outside
        with open(MODEL_PATH, "wb") as f:
            pickle.dump(model, f)
        LEARNING_PATH.write_text(json.dumps(report))
        logger.info(f"Model retrained on {len(rows)} examples; edge found: {report['edge_found']}; "
                    f"approval threshold {report['threshold']}")
        return model, report["threshold"]
    except Exception as e:
        logger.error(f"Retrain failed: {e}")
        return None


def load_model():
    if MODEL_PATH.exists():
        try:
            # Safe: the file is written only by retrain() in this app
            with open(MODEL_PATH, "rb") as f:
                model = pickle.load(f)
            # Verify the model expects the right number of features (10 market + 1 side = 11)
            expected = config.FEATURE_LEN + 1
            model.predict_proba([[0.0] * expected])
            return model
        except Exception as e:
            logger.warning(f"Discarding stale/incompatible model ({e}). Will retrain from scratch.")
            try:
                MODEL_PATH.unlink()
            except OSError:
                pass
    return None


def load_learning():
    try:
        return json.loads(LEARNING_PATH.read_text())
    except (OSError, ValueError):
        return None


def load_threshold() -> float:
    info = load_learning()
    if info and "threshold" in info:
        return float(info["threshold"])
    return config.ML_MIN_PROB


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


def write_seed(trades: list, path: Path = SEED_PATH) -> int:
    """Save historical trades to a file shipped with the app so any fresh server starts pre-trained."""
    path.parent.mkdir(exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "symbol", "entry", "exit_price", "pnl", "profitable", "features"])
        for t in trades:
            w.writerow([t.ts, t.symbol, t.entry, t.exit_price, t.pnl, t.profitable, json.dumps(t.features)])
    return len(trades)


def seed_from_file() -> int:
    """On a fresh database, load the shipped historical examples (current feature format only)."""
    if not SEED_PATH.exists():
        return 0
    with _conn() as con:
        stale = []
        for row_id, features_json in con.execute("SELECT id, features FROM trades WHERE source = 'backtest'").fetchall():
            try:
                ok = len(json.loads(features_json)) == config.FEATURE_LEN
            except (TypeError, ValueError):
                ok = False
            if not ok:
                stale.append((row_id,))
        if stale:
            con.executemany("DELETE FROM trades WHERE id = ?", stale)
            con.commit()
        if con.execute("SELECT COUNT(*) FROM trades WHERE source = 'backtest'").fetchone()[0] > 0:
            return 0
        rows = []
        with open(SEED_PATH, newline="") as f:
            for r in csv.DictReader(f):
                rows.append((r["ts"], r["symbol"], "buy", float(r["entry"]), float(r["exit_price"]),
                             float(r["pnl"]), int(r["profitable"]), r["features"], "backtest"))
        con.executemany(
            "INSERT INTO trades (ts, symbol, side, entry, exit_price, pnl, profitable, features, source) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    logger.info(f"Loaded {len(rows)} historical examples from the seed file.")
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

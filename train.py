"""
Pre-training: downloads real Binance history, simulates the strategy's candidate
trades, tests an ML filter on data it has NOT seen (chronological holdout),
then trains the final model on everything.

Run:  python train.py
"""
import logging
import os
import sys

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/train.log", encoding="utf-8")],
)
logger = logging.getLogger("train")

from sklearn.ensemble import GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from bot import config, learner
from bot.backtest import run_backtest, trades_to_stats
from bot.data_feed import get_public_exchange
from bot.history import fetch_full_history

HOLDOUT_FRACTION = 0.30
THRESHOLDS = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


def summarize(trades):
    n = len(trades)
    if n == 0:
        return None
    wins = sum(t.profitable for t in trades)
    gain = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
    loss = -sum(t.pnl_pct for t in trades if t.pnl_pct <= 0)
    return {
        "n": n,
        "win_rate": wins / n,
        "profit_factor": gain / loss if loss > 0 else float("inf"),
        "avg_ret": sum(t.pnl_pct for t in trades) / n,
    }


def line(label, s):
    if s is None:
        return f"  {label}: no trades"
    return (f"  {label}: {s['n']:>5} trades | win rate {s['win_rate']:.1%} | "
            f"profit factor {s['profit_factor']:.2f} | avg return/trade {s['avg_ret']:+.3%}")


def holdout_test(all_trades):
    trades = sorted(all_trades, key=lambda t: t.ts)
    split = int(len(trades) * (1 - HOLDOUT_FRACTION))
    train, test = trades[:split], trades[split:]
    if len(train) < 200 or len(test) < 50:
        logger.warning("Too few trades for a reliable holdout test.")
        return

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(n_estimators=100, learning_rate=0.05,
                                           max_depth=3, random_state=42)),
    ])
    model.fit([t.features for t in train], [t.profitable for t in train])
    probs = model.predict_proba([t.features for t in test])[:, 1]

    logger.info("")
    logger.info(f"OUT-OF-SAMPLE TEST (trained on older {len(train)} trades, scored on newest {len(test)}):")
    logger.info(line("No ML filter (all candidate trades)", summarize(test)))
    for th in THRESHOLDS:
        picked = [t for t, p in zip(test, probs) if p >= th]
        logger.info(line(f"ML prob >= {th:.2f}", summarize(picked)))
    logger.info("Look for a threshold with profit factor clearly above 1.0 AND enough trades.")
    logger.info("Then set ML_MIN_PROB=<that threshold> in .env")


def main():
    logger.info(f"Symbols: {config.SYMBOLS} | timeframe {config.TIMEFRAME}")
    learner.init_db()
    exchange = get_public_exchange()
    exchange.load_markets()

    all_trades = []
    for symbol in config.SYMBOLS:
        df = fetch_full_history(exchange, symbol, timeframe=config.TIMEFRAME, days=365 * 2)
        if df.empty:
            continue
        trades = run_backtest(df, symbol)
        if not trades:
            logger.warning(f"No candidate trades for {symbol}")
            continue
        logger.info(line(f"{symbol} candidates", summarize(trades)))
        all_trades.extend(trades)

    if not all_trades:
        logger.error("No trades generated. Check symbols and internet connection.")
        sys.exit(1)

    holdout_test(all_trades)

    learner.bulk_insert_trades(all_trades)
    model = learner.retrain()
    if not model:
        logger.error("Model training failed - not enough data.")
        sys.exit(1)
    logger.info("Final model trained on all data and saved.")


if __name__ == "__main__":
    main()

"""
Pre-training: replays recent real Binance history through the bot's rules, saves every simulated
trade as a labeled example in seed/backtest_trades.csv (shipped with the app so a fresh server
starts pre-trained), trains the model, and prints the out-of-sample test.

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

from bot import config, learner
from bot.backtest import run_backtest, trades_to_stats
from bot.data_feed import get_public_exchange
from bot.history import fetch_full_history

HISTORY_DAYS = int(os.getenv("TRAIN_DAYS", "180"))


def main():
    # Broad candidates (3 of 6 rules), the same ones the live "shadow trades" collect
    config.MIN_RULE_SCORE = config.SHADOW_MIN_SCORE
    logger.info(f"Symbols {config.SYMBOLS} | {config.TIMEFRAME} | last {HISTORY_DAYS} days | rules >= {config.MIN_RULE_SCORE}")

    learner.init_db()
    exchange = get_public_exchange()
    exchange.load_markets()

    all_trades = []
    for symbol in config.SYMBOLS:
        df = fetch_full_history(exchange, symbol, timeframe=config.TIMEFRAME, days=HISTORY_DAYS)
        if df.empty:
            continue
        trades = run_backtest(df, symbol)
        if trades:
            s = trades_to_stats(trades)
            logger.info(f"{symbol}: {s['total_trades']} trades | win rate {s['win_rate']:.1%} | profit factor {s['profit_factor']:.2f}")
            all_trades.extend(trades)

    if not all_trades:
        logger.error("No trades generated. Check symbols and internet connection.")
        sys.exit(1)

    written = learner.write_seed(all_trades)
    logger.info(f"Seed file written: {written} examples")

    import sqlite3
    with sqlite3.connect(learner.DB_PATH) as con:
        con.execute("DELETE FROM trades WHERE source = 'backtest'")
        con.commit()
    learner.bulk_insert_trades(all_trades)

    result = learner.retrain()
    if not result:
        logger.error("Training failed: not enough data.")
        sys.exit(1)

    info = learner.load_learning()
    logger.info("")
    logger.info(f"OUT-OF-SAMPLE TEST on the newest 25% ({info['rows']} examples in total)")
    b = info.get("baseline")
    if b:
        logger.info(f"  all setups (no model): {b['n']:>5} trades | win {b['win_rate']:.1%} | profit factor {b['profit_factor']:.2f} | avg {b['avg_ret']:+.3%}")
    for s in info.get("holdout", []):
        logger.info(f"  model win chance >= {s['threshold']:.2f}: {s['n']:>5} trades | win {s['win_rate']:.1%} | profit factor {s['profit_factor']:.2f} | avg {s['avg_ret']:+.3%}")
    logger.info(f"EDGE FOUND: {info['edge_found']} | approval threshold {info['threshold']}")


if __name__ == "__main__":
    main()

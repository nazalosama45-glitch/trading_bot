"""
Trading bot main loop.
Runs every candle close (polls every 60s), evaluates signals,
manages open positions, and retrains ML model periodically.
"""
import json
import os
import time
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from bot import config
from bot.data_feed import get_exchange, fetch_ohlcv, fetch_balance, fetch_ticker
from bot.indicators import compute_all
from bot.strategy import evaluate
from bot.risk_manager import RiskManager
from bot.safety_guard import SafetyGuard
from bot.executor import place_market_order, place_oco_order
from bot import learner

# ── Logging setup ─────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log"),
    ],
)
logger = logging.getLogger("main")

# ── Graceful shutdown ──────────────────────────────────────────────────────────
_running = True

def _handle_signal(sig, frame):
    global _running
    logger.info("Shutdown signal received. Stopping after current iteration...")
    _running = False

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


_last_usdt = None  # cash balance from the latest balance check


def get_portfolio_value(exchange: ccxt.Exchange) -> float:
    """Return approximate USDT portfolio value."""
    global _last_usdt
    if config.DRY_RUN:
        return 1000.0  # simulated capital
    balance = fetch_balance(exchange)
    usdt = balance.get("USDT", 0.0)
    _last_usdt = usdt
    total = usdt
    for sym in config.SYMBOLS:
        base = sym.split("/")[0]
        qty = balance.get(base, 0.0)
        if qty > 0:
            ticker = fetch_ticker(exchange, sym)
            total += qty * ticker.get("last", 0)
    return total


def refresh_cash(exchange: ccxt.Exchange):
    """Re-read the USDT balance right after an order, so cash and held coins never double count."""
    global _last_usdt
    if config.DRY_RUN:
        return
    usdt = fetch_balance(exchange).get("USDT")
    if usdt is not None:
        _last_usdt = usdt


def save_positions(risk: RiskManager, last_prices: dict):
    """Write open positions + live profit to a file the dashboard reads."""
    rows = []
    for sym, pos in risk.open_positions.items():
        price = last_prices.get(sym, pos["entry"])
        direction = 1 if pos["side"] == "buy" else -1
        rows.append({
            "symbol": sym,
            "side": pos["side"],
            "entry": pos["entry"],
            "price": price,
            "qty": pos["qty"],
            "stop_loss": pos["stop_loss"],
            "take_profit": pos["take_profit"],
            "features": pos.get("features", []),
            "pnl_pct": round(direction * (price - pos["entry"]) / pos["entry"] * 100, 3),
            "pnl_usd": round(direction * (price - pos["entry"]) * pos["qty"], 2),
        })
    account = {}
    if _last_usdt is not None:
        held = sum(r["qty"] * r["price"] for r in rows)
        account = {
            "cash_usdt": round(_last_usdt, 2),
            "held_value": round(held, 2),
            "equity": round(_last_usdt + held, 2),
            "start_capital": config.START_CAPITAL,
        }
    try:
        Path("data").mkdir(exist_ok=True)
        tmp = Path("data/positions.json.tmp")
        tmp.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "positions": rows, **account}))
        os.replace(tmp, "data/positions.json")
    except OSError as e:
        logger.warning(f"Could not write positions file: {e}")


def run():
    logger.info("=" * 60)
    logger.info(f"  Trading Bot starting  |  DRY_RUN={config.DRY_RUN}")
    logger.info(f"  Symbols: {config.SYMBOLS}")
    logger.info(f"  Timeframe: {config.TIMEFRAME}")
    if config.DRY_RUN:
        logger.info("  ⚠️  DRY RUN MODE — no real orders will be placed")
    elif config.USE_TESTNET:
        logger.info("  TESTNET: orders are real but the money is fake")
    else:
        logger.warning("  LIVE MODE: real money at risk!")
    logger.info("=" * 60)

    if config.PRACTICE_MODE and not config.USE_TESTNET:
        logger.error("PRACTICE_MODE is only allowed on the testnet. Set USE_TESTNET=true. Exiting.")
        return

    learner.init_db()
    exchange = get_exchange()
    exchange.load_markets()

    risk = RiskManager()
    try:
        saved = json.loads(Path("data/positions.json").read_text())
        for p in saved.get("positions", []):
            risk.open_positions[p["symbol"]] = {
                "side": p["side"], "entry": p["entry"], "qty": p["qty"],
                "stop_loss": p["stop_loss"], "take_profit": p["take_profit"],
                "features": p.get("features", []),
            }
        if risk.open_positions:
            logger.info(f"Restored open trades after restart: {list(risk.open_positions)}")
    except (OSError, ValueError, KeyError):
        pass
    guard = SafetyGuard()
    ml_model = learner.load_model()
    if ml_model:
        logger.info("Loaded existing ML model.")

    last_candle_time: dict = {}  # symbol -> last processed candle timestamp
    last_prices: dict = {}       # symbol -> latest price for open positions

    while _running:
        loop_start = time.time()

        portfolio_value = get_portfolio_value(exchange)
        logger.info(f"Portfolio value: ${portfolio_value:.2f} | Daily PnL: {risk.daily_pnl:.2%}")

        # ── Check open positions for SL/TP ────────────────────────────────────
        for symbol in list(risk.open_positions.keys()):
            ticker = fetch_ticker(exchange, symbol)
            price = ticker.get("last", 0)
            if price == 0:
                continue
            last_prices[symbol] = price
            hit = risk.check_sl_tp(symbol, price)
            if hit:
                logger.info(f"{symbol}: {'Stop-loss' if hit == 'sl' else 'Take-profit'} hit @ {price}")
                pos = risk.open_positions[symbol]
                close_side = "sell" if pos["side"] == "buy" else "buy"
                place_market_order(exchange, symbol, close_side, pos["qty"])
                pnl = risk.register_close(symbol, price)
                refresh_cash(exchange)
                profitable = pnl > 0
                guard.register_trade_result(profitable)
                learner.log_trade(
                    ts=datetime.now(timezone.utc).isoformat(),
                    symbol=symbol,
                    side=pos["side"],
                    entry=pos["entry"],
                    exit_price=price,
                    pnl=pnl / pos["qty"] if pos["qty"] else 0.0,
                    features=pos.get("features", []),
                    pnl_usd=pnl,
                )
                # Retrain check (counts only the bot's own live trades)
                count = learner.live_trade_count()
                if count % config.RETRAIN_EVERY == 0 and count > 0:
                    logger.info(f"Retraining ML model ({count} trades)...")
                    ml_model = learner.retrain() or ml_model

        # ── Scan for new signals ───────────────────────────────────────────────
        for symbol in config.SYMBOLS:
            if not _running:
                break
            try:
                df = fetch_ohlcv(exchange, symbol)
                if df.empty:
                    continue

                df = compute_all(df)
                if df.empty:
                    continue

                # Only act on a new completed candle
                latest_ts = str(df.index[-1])
                if last_candle_time.get(symbol) == latest_ts:
                    continue
                last_candle_time[symbol] = latest_ts

                signal = evaluate(df, symbol, ml_model)
                if signal is None:
                    continue

                allowed, reason = risk.can_open_trade(symbol)
                if not allowed:
                    logger.info(f"Trade blocked for {symbol}: {reason}")
                    continue

                size_mult = 1.0
                if not config.PRACTICE_MODE:
                    guard_result = guard.check(df, signal.confidence)
                    if not guard_result.allowed:
                        logger.info(f"SafetyGuard blocked {symbol}: {guard_result.reason}")
                        continue
                    size_mult = guard_result.size_multiplier

                qty = risk.position_size(portfolio_value, signal.entry_price, signal.stop_loss)
                qty *= size_mult
                if qty <= 0:
                    logger.warning(f"Computed zero qty for {symbol}, skipping")
                    continue

                logger.info(
                    f"Signal: {signal.side.upper()} {symbol} "
                    f"confidence={signal.confidence:.2f} "
                    f"entry={signal.entry_price} SL={signal.stop_loss} TP={signal.take_profit}"
                )

                order = place_market_order(exchange, symbol, signal.side, qty)
                if order:
                    # Store features with position for later logging
                    risk.open_positions.setdefault(symbol, {})
                    risk.register_open(
                        symbol, signal.side, signal.entry_price,
                        signal.stop_loss, signal.take_profit, qty
                    )
                    risk.open_positions[symbol]["features"] = signal.features
                    refresh_cash(exchange)
                    place_oco_order(
                        exchange, symbol, signal.side, qty,
                        signal.stop_loss, signal.take_profit
                    )

            except Exception as e:
                logger.exception(f"Error processing {symbol}: {e}")

        # ── Sleep until next check (60s) ───────────────────────────────────────
        save_positions(risk, last_prices)
        elapsed = time.time() - loop_start
        sleep_time = max(0, 20 - elapsed)
        logger.debug(f"Loop done in {elapsed:.1f}s. Sleeping {sleep_time:.1f}s...")
        for _ in range(int(sleep_time)):
            if not _running:
                break
            time.sleep(1)

    logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    run()

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
import threading
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from bot import config
from bot.data_feed import get_exchange, fetch_ohlcv, fetch_balance, fetch_ticker
from bot.indicators import compute_all
from bot.strategy import candidate, decide
from bot.shadow import ShadowBook
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


def get_portfolio_value(exchange: ccxt.Exchange, risk=None) -> float:
    """Return approximate USDT portfolio value."""
    global _last_usdt
    if config.DRY_RUN:
        return 1000.0  # simulated capital
    balance = fetch_balance(exchange)
    usdt = balance.get("USDT", 0.0)
    _last_usdt = usdt
    # Only the bot's own open trades count; testnet pre-loads every account with other coins
    total = usdt
    for sym, pos in (risk.open_positions.items() if risk else []):
        total += pos["qty"] * (fetch_ticker(exchange, sym).get("last") or pos["entry"])
    return total


def _retrain_job(state: dict):
    """Runs in a background thread so a slow training run never pauses trading."""
    try:
        state["result"] = learner.retrain()
    finally:
        state["busy"] = False


def refresh_cash(exchange: ccxt.Exchange):
    """Re-read the USDT balance right after an order, so cash and held coins never double count."""
    global _last_usdt
    if config.DRY_RUN:
        return
    usdt = fetch_balance(exchange).get("USDT")
    if usdt is not None:
        _last_usdt = usdt


def save_positions(risk: RiskManager, last_prices: dict, portfolio_value: float = None):
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
        # Only count cash + positions the bot itself opened (not testnet pre-loaded balances)
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
    seeded = learner.seed_from_file()
    if seeded:
        logger.info(f"Starting pre-trained: loaded {seeded} historical examples.")
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
    threshold = learner.load_threshold()
    if ml_model:
        logger.info(f"Loaded existing ML model (approval threshold {threshold:.2f}).")

    shadow = ShadowBook()
    shadow_seen: dict = {}       # symbol -> candle already shadowed
    last_attempt: dict = {}      # symbol -> candle already considered for a real trade
    cooldown_until: dict = {}    # symbol -> time before which no new trade is attempted
    last_prices: dict = {}       # symbol -> latest price for open positions
    retrain_state = {"busy": False, "result": None}
    trained_rows = learner.labeled_count() if ml_model else 0  # 0 = never trained yet

    while _running:
        loop_start = time.time()

        portfolio_value = get_portfolio_value(exchange, risk)
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
                cooldown_until[symbol] = time.time() + config.COOLDOWN_SECONDS
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
        # ── Learning: retrain in the background as new labeled examples arrive ──
        if retrain_state["result"] is not None:
            ml_model, threshold = retrain_state["result"]
            retrain_state["result"] = None
            logger.info(f"Switched to the retrained model (approval threshold {threshold:.2f}).")
        n_labeled = learner.labeled_count()
        if (not retrain_state["busy"] and n_labeled >= 100
                and (trained_rows == 0 or n_labeled - trained_rows >= config.RETRAIN_EVERY_ROWS)):
            retrain_state["busy"] = True
            trained_rows = n_labeled
            logger.info(f"Retraining the model on {n_labeled} labeled examples...")
            threading.Thread(target=_retrain_job, args=(retrain_state,), daemon=True).start()

        # ── Scan every coin: follow shadow trades, then look for new setups ────
        for symbol in config.SYMBOLS:
            if not _running:
                break
            try:
                raw = fetch_ohlcv(exchange, symbol)
                if raw.empty or len(raw) < 60:
                    continue
                price = float(raw["close"].iloc[-1])    # live price
                df = compute_all(raw.iloc[:-1])         # completed candles only, so volume is final
                if df.empty:
                    continue
                candle_ts = str(df.index[-1])

                for done in shadow.update(symbol, price):
                    learner.log_shadow(done)

                scan_score = config.SHADOW_MIN_SCORE if config.SHADOW_ENABLED else config.MIN_RULE_SCORE
                signal = candidate(df, symbol, min_score=scan_score, price=price)
                if signal is None:
                    continue
                score = round(signal.confidence * 4)

                # One pretend BUY and one pretend SELL, so it learns which direction wins here
                if config.SHADOW_ENABLED and shadow_seen.get(symbol) != candle_ts:
                    shadow.add_both(symbol, signal, candle_ts)
                    shadow_seen[symbol] = candle_ts

                if score < config.MIN_RULE_SCORE or last_attempt.get(symbol) == candle_ts:
                    continue
                if symbol in risk.open_positions or time.time() < cooldown_until.get(symbol, 0):
                    continue
                last_attempt[symbol] = candle_ts

                if not decide(signal, ml_model, threshold):
                    logger.info(f"Model skipped {symbol}: win chance {signal.confidence:.2f} is below {threshold:.2f}")
                    continue

                allowed, reason = risk.can_open_trade(symbol)
                if not allowed:
                    continue

                cooldown_until[symbol] = time.time() + config.COOLDOWN_SECONDS

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
        save_positions(risk, last_prices, portfolio_value)
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

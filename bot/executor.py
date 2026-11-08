"""
Order executor: places real orders on Binance, or simulates them in DRY_RUN mode.
"""
import logging
import ccxt
from bot import config

logger = logging.getLogger(__name__)


def _format_qty(exchange: ccxt.Exchange, symbol: str, qty: float) -> float:
    """Round qty to exchange precision."""
    try:
        market = exchange.market(symbol)
        precision = market.get("precision", {}).get("amount", 8)
        return float(exchange.amount_to_precision(symbol, qty))
    except Exception:
        return round(qty, 6)


def place_market_order(exchange: ccxt.Exchange, symbol: str, side: str, qty: float) -> dict | None:
    qty = _format_qty(exchange, symbol, qty)
    if qty <= 0:
        logger.warning(f"Invalid qty {qty} for {symbol}")
        return None

    if config.DRY_RUN:
        logger.info(f"[DRY RUN] {side.upper()} {qty} {symbol}")
        return {"id": "dry_run", "symbol": symbol, "side": side, "amount": qty, "status": "closed"}

    try:
        order = exchange.create_market_order(symbol, side, qty)
        logger.info(f"Order filled: {side.upper()} {qty} {symbol} @ {order.get('average')} (id {order.get('id')})")
        return order
    except ccxt.InsufficientFunds as e:
        logger.error(f"Insufficient funds for {symbol}: {e}")
    except ccxt.InvalidOrder as e:
        logger.error(f"Invalid order {symbol}: {e}")
    except Exception as e:
        logger.error(f"Order failed {symbol}: {e}")
    return None


def place_oco_order(exchange: ccxt.Exchange, symbol: str, side: str,
                    qty: float, stop_loss: float, take_profit: float) -> dict | None:
    """Place OCO (One-Cancels-Other) for SL+TP. Falls back to manual management if unsupported."""
    qty = _format_qty(exchange, symbol, qty)
    if qty <= 0:
        return None

    if config.DRY_RUN:
        logger.info(f"[DRY RUN] OCO {side} {qty} {symbol} SL={stop_loss} TP={take_profit}")
        return {"id": "dry_run_oco", "sl": stop_loss, "tp": take_profit}

    try:
        # Binance spot OCO
        close_side = "sell" if side == "buy" else "buy"
        order = exchange.create_order(
            symbol, "OCO", close_side, qty,
            price=take_profit,
            params={"stopPrice": stop_loss, "stopLimitPrice": stop_loss * 0.999}
        )
        logger.info(f"OCO order placed: {order}")
        return order
    except Exception as e:
        logger.warning(f"OCO not supported or failed ({e}). Will manage SL/TP manually.")
        return None

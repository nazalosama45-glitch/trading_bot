import logging
from datetime import date
from bot import config

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self):
        self.daily_pnl: float = 0.0
        self.daily_date: date = date.today()
        self.open_positions: dict = {}   # symbol -> position dict

    def _reset_daily_if_needed(self):
        today = date.today()
        if today != self.daily_date:
            self.daily_pnl = 0.0
            self.daily_date = today

    def can_open_trade(self, symbol: str) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        self._reset_daily_if_needed()

        if symbol in self.open_positions:
            return False, f"Already have an open position in {symbol}"

        if len(self.open_positions) >= config.MAX_OPEN_POSITIONS:
            return False, f"Max open positions ({config.MAX_OPEN_POSITIONS}) reached"

        if self.daily_pnl <= -config.DAILY_LOSS_LIMIT_PCT:
            return False, f"Daily loss limit hit ({self.daily_pnl:.2%})"

        return True, ""

    def position_size(self, portfolio_value: float, entry: float, stop_loss: float) -> float:
        """Kelly-lite: risk MAX_POSITION_PCT of portfolio, sized to the SL distance."""
        risk_amount = portfolio_value * config.MAX_POSITION_PCT
        sl_distance = abs(entry - stop_loss)
        if sl_distance == 0:
            return 0.0
        qty = risk_amount / sl_distance
        # Also cap by max 10% of portfolio at current price
        max_qty = (portfolio_value * config.MAX_NOTIONAL_PCT) / entry
        return min(qty, max_qty)

    def register_open(self, symbol: str, side: str, entry: float,
                      stop_loss: float, take_profit: float, qty: float):
        self.open_positions[symbol] = {
            "side": side,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "qty": qty,
        }
        logger.info(f"Position opened: {side} {qty:.6f} {symbol} @ {entry}")

    def register_close(self, symbol: str, exit_price: float) -> float:
        """Close position, update PnL, return realized PnL."""
        if symbol not in self.open_positions:
            return 0.0
        pos = self.open_positions.pop(symbol)
        if pos["side"] == "buy":
            pnl = (exit_price - pos["entry"]) * pos["qty"]
        else:
            pnl = (pos["entry"] - exit_price) * pos["qty"]
        pnl_pct = pnl / (pos["entry"] * pos["qty"]) if pos["entry"] * pos["qty"] else 0
        self.daily_pnl += pnl_pct
        logger.info(f"Position closed: {symbol} exit={exit_price} PnL={pnl:.4f} ({pnl_pct:.2%})")
        return pnl

    def check_sl_tp(self, symbol: str, current_price: float) -> str | None:
        """Returns 'sl', 'tp', or None."""
        pos = self.open_positions.get(symbol)
        if not pos:
            return None
        if pos["side"] == "buy":
            if current_price <= pos["stop_loss"]:
                return "sl"
            if current_price >= pos["take_profit"]:
                return "tp"
        else:
            if current_price >= pos["stop_loss"]:
                return "sl"
            if current_price <= pos["take_profit"]:
                return "tp"
        return None

"""
Shadow trades: pretend trades on every setup the bot sees. No orders are placed. Each one is
followed to its stop-loss, take-profit or a time limit, then logged as a labeled example.
This gives the model far more to learn from than the few real trades the account can hold.
"""
import time
from dataclasses import dataclass
from typing import Optional

FEE_RATE = 0.001          # 0.1% each side, same as the backtest
MAX_AGE_SECONDS = 12 * 3600


@dataclass
class ShadowTrade:
    symbol: str
    entry: float
    stop_loss: float
    take_profit: float
    features: list
    opened_at: float
    candle_ts: str


class ShadowBook:
    def __init__(self):
        self.open: dict = {}
        self.closed_total = 0

    def has(self, symbol: str) -> bool:
        return symbol in self.open

    def add(self, symbol: str, signal, candle_ts: str):
        self.open[symbol] = ShadowTrade(
            symbol=symbol, entry=signal.entry_price, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit, features=signal.features,
            opened_at=time.time(), candle_ts=candle_ts,
        )

    def update(self, symbol: str, price: float) -> Optional[dict]:
        """Check one open shadow trade against the live price. Returns a result dict if it closed."""
        t = self.open.get(symbol)
        if t is None:
            return None
        if price <= t.stop_loss:
            exit_price, reason = t.stop_loss, "sl"
        elif price >= t.take_profit:
            exit_price, reason = t.take_profit, "tp"
        elif time.time() - t.opened_at >= MAX_AGE_SECONDS:
            exit_price, reason = price, "timeout"
        else:
            return None
        del self.open[symbol]
        self.closed_total += 1
        pnl_pct = (exit_price - t.entry) / t.entry - 2 * FEE_RATE
        return {
            "symbol": symbol, "entry": t.entry, "exit": exit_price, "pnl_pct": pnl_pct,
            "profitable": 1 if pnl_pct > 0 else 0, "features": t.features, "reason": reason,
        }

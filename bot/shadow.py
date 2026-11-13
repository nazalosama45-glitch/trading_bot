"""
Shadow trades: pretend trades on every setup the bot sees. No orders are placed.

Each setup opens TWO pretend trades at the same moment: one betting the price rises (buy) and
one betting it falls (sell). Both are followed to their stop-loss, take-profit or a time limit,
then logged as labeled examples. That teaches the model which DIRECTION a setup favours, not
just whether to trade, and it doubles the practice data at no cost.
"""
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

FEE_RATE = 0.001          # 0.1% each side, same as the backtest
MAX_AGE_SECONDS = 12 * 3600
SAVE_PATH = Path("data/shadow.json")


@dataclass
class ShadowTrade:
    symbol: str
    side: str             # "buy" (bet on a rise) or "sell" (bet on a fall)
    entry: float
    stop_loss: float
    take_profit: float
    features: list
    opened_at: float
    candle_ts: str


class ShadowBook:
    def __init__(self):
        self.open: dict = {}          # (symbol, side) -> ShadowTrade
        self.closed_total = 0

    @classmethod
    def load(cls) -> "ShadowBook":
        """Pick up the pretend trades that were still running before a restart."""
        book = cls()
        try:
            for row in json.loads(SAVE_PATH.read_text()):
                t = ShadowTrade(**row)
                book.open[(t.symbol, t.side)] = t
        except (OSError, ValueError, TypeError):
            pass
        return book

    def save(self):
        try:
            SAVE_PATH.parent.mkdir(exist_ok=True)
            tmp = SAVE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(t) for t in self.open.values()]))
            os.replace(tmp, SAVE_PATH)
        except OSError:
            pass

    def has(self, symbol: str, side: str = "buy") -> bool:
        return (symbol, side) in self.open

    def add(self, symbol: str, signal, candle_ts: str, side: str = "buy"):
        """Open one pretend trade. For "sell" the exits are mirrored around the entry price."""
        entry = signal.entry_price
        if side == "buy":
            sl, tp = signal.stop_loss, signal.take_profit
        else:
            sl = entry + (entry - signal.stop_loss)      # same distance, other direction
            tp = entry - (signal.take_profit - entry)
        self.open[(symbol, side)] = ShadowTrade(
            symbol=symbol, side=side, entry=entry, stop_loss=sl, take_profit=tp,
            features=signal.features, opened_at=time.time(), candle_ts=candle_ts,
        )

    def add_both(self, symbol: str, signal, candle_ts: str):
        for side in ("buy", "sell"):
            if not self.has(symbol, side):
                self.add(symbol, signal, candle_ts, side)

    def update(self, symbol: str, price: float) -> list:
        """Check this coin's open pretend trades against the live price. Returns those that closed."""
        done = []
        for side in ("buy", "sell"):
            t = self.open.get((symbol, side))
            if t is None:
                continue
            if side == "buy":
                hit_sl, hit_tp = price <= t.stop_loss, price >= t.take_profit
            else:
                hit_sl, hit_tp = price >= t.stop_loss, price <= t.take_profit

            if hit_sl:
                exit_price, reason = t.stop_loss, "sl"
            elif hit_tp:
                exit_price, reason = t.take_profit, "tp"
            elif time.time() - t.opened_at >= MAX_AGE_SECONDS:
                exit_price, reason = price, "timeout"
            else:
                continue

            del self.open[(symbol, side)]
            self.closed_total += 1
            raw = (exit_price - t.entry) if side == "buy" else (t.entry - exit_price)
            pnl_pct = raw / t.entry - 2 * FEE_RATE
            done.append({
                "symbol": symbol, "side": side, "entry": t.entry, "exit": exit_price,
                "pnl_pct": pnl_pct, "profitable": 1 if pnl_pct > 0 else 0,
                "features": t.features, "reason": reason,
            })
        return done

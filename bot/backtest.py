"""
Backtester: replays strategy over historical data, labels every signal
win/loss based on what actually happened, then bulk-inserts to the trade DB
so the ML model can train on thousands of historical examples.
"""
import logging
from datetime import timezone, datetime
from dataclasses import dataclass
from typing import List

import pandas as pd

from bot import config
from bot.indicators import compute_all, feature_vector
from bot.strategy import evaluate

logger = logging.getLogger(__name__)

FEE_RATE = 0.001   # 0.1% taker fee each side


@dataclass
class BacktestTrade:
    ts: str
    symbol: str
    side: str
    entry: float
    exit_price: float
    pnl: float          # in price terms (not %)
    pnl_pct: float
    profitable: int
    features: list
    exit_reason: str    # "tp", "sl", "timeout"


def run_backtest(df_raw: pd.DataFrame, symbol: str) -> List[BacktestTrade]:
    """
    Walk candle-by-candle, fire signals, simulate the trade to SL/TP.
    Returns a list of BacktestTrade results.
    """
    df = compute_all(df_raw)
    if df.empty:
        return []

    trades: List[BacktestTrade] = []
    in_trade = False
    side = entry = sl = tp = entry_features = None
    entry_idx = None
    MAX_BARS_IN_TRADE = 48  # close after 48 bars if SL/TP not hit (~12h on 15m)

    for i in range(50, len(df)):
        window = df.iloc[:i]
        current = df.iloc[i]
        price = current["close"]

        if in_trade:
            bars_held = i - entry_idx
            hit = None

            if side == "buy":
                if current["low"] <= sl:
                    hit, exit_price = "sl", sl
                elif current["high"] >= tp:
                    hit, exit_price = "tp", tp
            else:
                if current["high"] >= sl:
                    hit, exit_price = "sl", sl
                elif current["low"] <= tp:
                    hit, exit_price = "tp", tp

            if hit is None and bars_held >= MAX_BARS_IN_TRADE:
                hit, exit_price = "timeout", price

            if hit:
                fee = entry * FEE_RATE + exit_price * FEE_RATE
                if side == "buy":
                    raw_pnl = exit_price - entry - fee
                else:
                    raw_pnl = entry - exit_price - fee

                pnl_pct = raw_pnl / entry
                trades.append(BacktestTrade(
                    ts=str(current.name),
                    symbol=symbol,
                    side=side,
                    entry=entry,
                    exit_price=exit_price,
                    pnl=raw_pnl,
                    pnl_pct=pnl_pct,
                    profitable=1 if raw_pnl > 0 else 0,
                    features=entry_features,
                    exit_reason=hit,
                ))
                in_trade = False

        else:
            # Look for a new signal
            signal = evaluate(window, symbol, ml_model=None)
            if signal:
                in_trade = True
                side = signal.side
                entry = signal.entry_price
                sl = signal.stop_loss
                tp = signal.take_profit
                entry_features = signal.features
                entry_idx = i

    return trades


def trades_to_stats(trades: List[BacktestTrade]) -> dict:
    if not trades:
        return {}
    total = len(trades)
    wins = sum(t.profitable for t in trades)
    pnl_pcts = [t.pnl_pct for t in trades]
    avg_win = sum(p for p in pnl_pcts if p > 0) / max(1, wins)
    avg_loss = sum(p for p in pnl_pcts if p <= 0) / max(1, total - wins)
    total_pnl = sum(pnl_pcts)

    # Simple drawdown
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for p in pnl_pcts:
        equity *= (1 + p)
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)

    return {
        "total_trades": total,
        "win_rate": wins / total,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": abs(avg_win * wins / (avg_loss * (total - wins))) if avg_loss != 0 else float("inf"),
        "total_return": total_pnl,
        "max_drawdown": max_dd,
        "sl_exits": sum(1 for t in trades if t.exit_reason == "sl"),
        "tp_exits": sum(1 for t in trades if t.exit_reason == "tp"),
        "timeout_exits": sum(1 for t in trades if t.exit_reason == "timeout"),
    }

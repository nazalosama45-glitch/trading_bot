import logging
import random
import pandas as pd
from dataclasses import dataclass
from typing import Optional
from bot import config
from bot.indicators import feature_vector

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    symbol: str
    side: str           # always "buy" (spot, long-only)
    confidence: float   # rule score / 6, replaced by the model's win chance once decide() runs
    stop_loss: float
    take_profit: float
    entry_price: float
    features: list      # for ML logging


def candidate(df: pd.DataFrame, symbol: str, min_score: Optional[int] = None,
              price: Optional[float] = None) -> Optional[Signal]:
    """
    Rule-based long setup read from the LAST row of df. Pass completed candles only,
    so volume and indicators are final. `price` is where the order would really fill.
    """
    if df.empty or len(df) < 50:
        return None

    last = df.iloc[-1]
    atr = last["atr"]
    if atr == 0:
        return None

    conditions = [
        last["ema_fast"] > last["ema_slow"],
        40 < last["rsi"] < 70,
        last["macd_hist"] > 0,
        last["vol_ratio"] > 1.0,
        last["close"] > last["ema_200"],
        last["bb_pct"] > 0.4,
    ]
    score = sum(conditions)
    if score < (config.MIN_RULE_SCORE if min_score is None else min_score):
        return None

    entry = float(price) if price else float(last["close"])
    return Signal(
        symbol=symbol,
        side="buy",
        confidence=score / 6.0,
        stop_loss=round(entry - atr * config.ATR_SL_MULT, 6),
        take_profit=round(entry + atr * config.ATR_TP_MULT, 6),
        entry_price=entry,
        features=feature_vector(last),
    )


def win_chance(ml_model, features: list, side: str) -> Optional[float]:
    """The model's estimated chance that betting this direction wins."""
    if ml_model is None:
        return None
    from bot.learner import with_side
    try:
        return float(ml_model.predict_proba([with_side(features, side)])[0][1])
    except Exception as e:
        logger.warning(f"ML prediction failed: {e}")
        return None


def decide(signal: Signal, ml_model, threshold: float) -> bool:
    """Take a real trade? Follow the model, but sometimes explore what it would skip."""
    prob = win_chance(ml_model, signal.features, signal.side)
    if prob is None:
        return True
    signal.confidence = prob
    if prob >= threshold:
        return True
    return random.random() < config.EXPLORE_RATE


def evaluate(df: pd.DataFrame, symbol: str, ml_model=None, threshold: Optional[float] = None,
             price: Optional[float] = None) -> Optional[Signal]:
    """Rules, then the model's say-so. Used by the backtester (no model) and by older callers."""
    sig = candidate(df, symbol, price=price)
    if sig is None or ml_model is None:
        return sig
    limit = config.ML_MIN_PROB if threshold is None else threshold
    return sig if decide(sig, ml_model, limit) else None

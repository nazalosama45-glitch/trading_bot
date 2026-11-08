import logging
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
    confidence: float   # 0-1
    stop_loss: float
    take_profit: float
    entry_price: float
    features: list      # for ML logging


def evaluate(df: pd.DataFrame, symbol: str, ml_model=None) -> Optional[Signal]:
    """
    Long-only. Rules generate candidate setups; the ML model (if trained)
    must then rate the candidate at least ML_MIN_PROB to be taken.
    """
    if df.empty or len(df) < 50:
        return None

    last = df.iloc[-1]
    entry = last["close"]
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
    rule_score = sum(conditions)
    if rule_score < 5:
        return None

    features = feature_vector(last)
    confidence = rule_score / 6.0

    if ml_model is not None:
        try:
            ml_prob = float(ml_model.predict_proba([features])[0][1])
        except Exception as e:
            logger.warning(f"ML prediction failed: {e}")
            return None
        if ml_prob < config.ML_MIN_PROB:
            return None
        confidence = ml_prob

    return Signal(
        symbol=symbol,
        side="buy",
        confidence=confidence,
        stop_loss=round(entry - atr * config.ATR_SL_MULT, 6),
        take_profit=round(entry + atr * config.ATR_TP_MULT, 6),
        entry_price=entry,
        features=features,
    )

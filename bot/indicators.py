import pandas as pd
import numpy as np


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicator columns to df. Returns enriched dataframe."""
    df = df.copy()
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    vol = df["volume"]

    # --- Trend ---
    df["ema_fast"] = c.ewm(span=9, adjust=False).mean()
    df["ema_slow"] = c.ewm(span=21, adjust=False).mean()
    df["ema_200"] = c.ewm(span=200, adjust=False).mean()
    df["trend_up"] = (df["ema_fast"] > df["ema_slow"]).astype(int)

    # --- Momentum: RSI ---
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # --- Volatility: ATR & Bollinger Bands ---
    tr = pd.concat([
        h - lo,
        (h - c.shift()).abs(),
        (lo - c.shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()

    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_pct"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # --- Volume ---
    df["vol_sma"] = vol.rolling(20).mean()
    df["vol_ratio"] = vol / df["vol_sma"].replace(0, np.nan)

    # --- MACD ---
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # --- Price-independent features, so lessons carry across coins ---
    df["atr_pct"] = df["atr"] / c
    df["macd_pct"] = df["macd_hist"] / c
    df["ret_4"] = c.pct_change(4)
    df["rsi_chg"] = df["rsi"].diff(3)

    # --- Composite signal score (rule-based, pre-ML) ---
    score = pd.Series(0.0, index=df.index)
    score += df["trend_up"] * 1.0
    score += ((df["rsi"] > 50) & (df["rsi"] < 70)).astype(float) * 1.0
    score += (df["macd_hist"] > 0).astype(float) * 1.0
    score += (df["vol_ratio"] > 1.2).astype(float) * 0.5
    score += (df["bb_pct"] > 0.4).astype(float) * 0.5
    df["signal_score"] = score

    return df.dropna()


def feature_vector(row: pd.Series) -> list:
    """Extract ML feature vector from an indicator row."""
    return [float(v) for v in (
        row["rsi"],
        row["macd_pct"],
        row["bb_pct"],
        row["vol_ratio"],
        row["trend_up"],
        row["ema_fast"] / row["ema_slow"] - 1,
        row["close"] / row["ema_200"] - 1,
        row["atr_pct"],
        row["ret_4"],
        row["rsi_chg"],
    )]

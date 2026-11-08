"""
Download full historical OHLCV from Binance — no API key needed for public data.
Fetches in 1000-candle chunks and stitches them together.
"""
import time
import logging
import pandas as pd
import ccxt

logger = logging.getLogger(__name__)

# How far back to fetch (in days)
DEFAULT_DAYS = 365 * 2   # 2 years


def fetch_full_history(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str = "15m",
    days: int = DEFAULT_DAYS,
) -> pd.DataFrame:
    """
    Returns a DataFrame with all OHLCV candles going back `days` days.
    Uses paginated requests (Binance allows up to 1000 per call).
    """
    ms_per_candle = _tf_to_ms(timeframe)
    since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000

    all_candles = []
    logger.info(f"Downloading {days}d of {timeframe} history for {symbol}...")

    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            time.sleep(5)
            continue

        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]

        if last_ts >= exchange.milliseconds() - ms_per_candle:
            break  # reached present

        since = last_ts + ms_per_candle
        time.sleep(exchange.rateLimit / 1000)  # respect rate limit

        if len(all_candles) % 10000 == 0:
            logger.info(f"  Downloaded {len(all_candles):,} candles so far...")

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df.astype(float)
    df = df[~df.index.duplicated(keep="first")]
    df.sort_index(inplace=True)

    logger.info(f"Downloaded {len(df):,} candles for {symbol} ({df.index[0]} to {df.index[-1]})")
    return df


def _tf_to_ms(timeframe: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    num = int(timeframe[:-1])
    unit = timeframe[-1]
    return num * units[unit]

import ccxt
import pandas as pd
import logging
from bot import config

logger = logging.getLogger(__name__)


def get_exchange() -> ccxt.Exchange:
    exchange = ccxt.binance({
        "apiKey": config.API_KEY,
        "secret": config.API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if config.USE_TESTNET:
        exchange.set_sandbox_mode(True)
    return exchange


def get_public_exchange() -> ccxt.Exchange:
    """Real Binance public market data (no keys, never testnet). Used for history/training."""
    return ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})


def fetch_ohlcv(exchange: ccxt.Exchange, symbol: str, timeframe: str = None, limit: int = None) -> pd.DataFrame:
    tf = timeframe or config.TIMEFRAME
    lim = limit or config.CANDLE_LIMIT
    try:
        raw = exchange.fetch_ohlcv(symbol, tf, limit=lim)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        return pd.DataFrame()


def fetch_balance(exchange: ccxt.Exchange) -> dict:
    try:
        balance = exchange.fetch_balance()
        return balance.get("total", {})
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        return {}


def fetch_ticker(exchange: ccxt.Exchange, symbol: str) -> dict:
    try:
        return exchange.fetch_ticker(symbol)
    except Exception as e:
        logger.error(f"Error fetching ticker {symbol}: {e}")
        return {}

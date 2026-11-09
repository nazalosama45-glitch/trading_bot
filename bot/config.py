import os
from dotenv import load_dotenv

load_dotenv(override=True)

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_SECRET", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
USE_TESTNET = os.getenv("USE_TESTNET", "false").lower() == "true"

SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT").split(",")]
TIMEFRAME = os.getenv("TIMEFRAME", "15m")

MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.02"))
DAILY_LOSS_LIMIT_PCT = float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.05"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "3"))

# How many candles to fetch for indicator calculation
CANDLE_LIMIT = 200

# ATR multipliers for SL/TP
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0

# Play-money starting balance shown on the dashboard
START_CAPITAL = float(os.getenv("START_CAPITAL", "10000"))

# Practice mode (testnet only): trade as much as possible to collect learning data.
# Turns off the SafetyGuard so the bot takes every rule-based setup.
PRACTICE_MODE = os.getenv("PRACTICE_MODE", "false").lower() == "true"

# Max size of one position as a share of the portfolio
MAX_NOTIONAL_PCT = float(os.getenv("MAX_NOTIONAL_PCT", "0.10"))

# How often the bot looks for trades. True = every pass (about every 20s) using the live candle;
# False = once per new candle. MIN_RULE_SCORE is how many of the 6 entry rules must agree.
SCAN_EVERY_LOOP = os.getenv("SCAN_EVERY_LOOP", "false").lower() == "true"
MIN_RULE_SCORE = int(os.getenv("MIN_RULE_SCORE", "5"))
# Pause on a coin after a trade attempt or close, so it can't re-enter instantly
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))

# Minimum ML win-probability required to take a trade (tuned by train.py's holdout test)
ML_MIN_PROB = float(os.getenv("ML_MIN_PROB", "0.5"))

# Learning: retrain model every N completed trades
RETRAIN_EVERY = 20

EXCHANGE_ID = "binance"

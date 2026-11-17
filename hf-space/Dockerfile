FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Changes whenever the GitHub repo changes, so a rebuild always pulls the newest code.
ADD https://api.github.com/repos/nazalosama45-glitch/trading_bot/git/refs/heads/main /tmp/version.json
RUN git clone --depth 1 https://github.com/nazalosama45-glitch/trading_bot.git . \
    && pip install --no-cache-dir -r requirements.txt \
    && chown -R user:user /home/user/app
USER user

# Secrets (DATABASE_URL, BINANCE_API_KEY, BINANCE_SECRET, DASHBOARD_PASSWORD) are set in the Space settings, never here.
ENV PORT=7860 \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_USER=admin \
    DASHBOARD_PUBLIC_READ=true \
    DASHBOARD_PUBLIC_CONTROL=true \
    AUTOSTART_BOT=true \
    START_DELAY_SECONDS=15 \
    USE_TESTNET=true \
    DRY_RUN=false \
    PRACTICE_MODE=true \
    SYMBOLS=BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT,XRP/USDT,ADA/USDT,DOGE/USDT,LINK/USDT,LTC/USDT,AVAX/USDT \
    TIMEFRAME=1h \
    SCAN_EVERY_LOOP=true \
    MIN_RULE_SCORE=2 \
    SHADOW_MIN_SCORE=1 \
    MAX_HOLD_HOURS=2 \
    COOLDOWN_SECONDS=300 \
    EXPLORE_RATE=1.0 \
    ML_MIN_PROB=0 \
    MAX_OPEN_POSITIONS=10 \
    DAILY_LOSS_LIMIT_PCT=1.0 \
    MAX_NOTIONAL_PCT=0.01 \
    MAX_POSITION_PCT=0.02 \
    START_CAPITAL=7271

EXPOSE 7860
CMD ["python", "dashboard/server.py"]

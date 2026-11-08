# Trading Bot — Setup Guide

## 1. Install Python dependencies
```bash
pip install -r requirements.txt
```

## 2. Configure your keys
```bash
cp .env.example .env
```
Edit `.env` and fill in:
- `BINANCE_API_KEY` and `BINANCE_SECRET` from your Binance account → API Management
- Keep `DRY_RUN=true` until you've watched at least 50+ paper trades

## 3. Run the bot
```bash
python main.py
```
Logs go to `logs/bot.log` and console.

## 4. When to switch to live
Only flip `DRY_RUN=false` after:
- [ ] 50+ paper trades logged in `data/trades.db`
- [ ] Win rate > 50% in paper mode
- [ ] ML model has trained at least once (20+ trades)
- [ ] You understand every loss and why it happened

## Architecture
```
main.py           ← 24/7 loop, orchestration
bot/
  config.py       ← all settings via .env
  data_feed.py    ← Binance OHLCV + balance
  indicators.py   ← EMA, RSI, MACD, ATR, BB, volume
  strategy.py     ← rule-based signals + ML confidence
  risk_manager.py ← position sizing, SL/TP, daily limits
  executor.py     ← place orders (DRY_RUN-aware)
  learner.py      ← SQLite trade log + ML retraining
data/trades.db    ← trade history
models/model.pkl  ← trained ML model (auto-updated)
logs/bot.log      ← full log
```

## How the bot learns
1. Every closed trade writes: entry conditions (7 indicator features) + profit/loss to SQLite
2. Every 20 trades, a GradientBoosting classifier retrains on that history
3. Future signals blend rule-based score (40%) + ML confidence (60%)
4. Over time, the ML learns which market conditions actually lead to profits for YOUR symbols

## Risk defaults (edit in .env)
| Setting | Default | Meaning |
|---|---|---|
| MAX_POSITION_PCT | 2% | Risk per trade |
| DAILY_LOSS_LIMIT_PCT | 5% | Bot stops trading for the day |
| MAX_OPEN_POSITIONS | 3 | Max concurrent trades |
| ATR_SL_MULT | 1.5× | Stop-loss distance |
| ATR_TP_MULT | 3.0× | Take-profit distance (2:1 R:R) |

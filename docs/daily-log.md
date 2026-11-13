# Trading bot daily log

## 2026-11-13
- ~4 days of training: 349 trades, 45% win rate, avg win +1.0% / avg loss -1.5%, money $6,560 (started $7,271; ~$646 lost to restart bug, not trading).
- Model holdout profit factor 0.56, no edge yet.
- Changes: fixed lost trades on restart (delayed start + reload + immediate backup), pretend trades persisted, training on current-strategy data only (300+ rows).
- Next: let it run untouched a few days; watch first retrain on new data.

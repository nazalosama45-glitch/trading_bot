# Trading bot daily log

## 2026-11-13
- ~4 days of training: 349 trades, 45% win rate, avg win +1.0% / avg loss -1.5%, money $6,560 (started $7,271; ~$646 lost to restart bug, not trading).
- Model holdout profit factor 0.56, no edge yet.
- Changes: fixed lost trades on restart (delayed start + reload + immediate backup), pretend trades persisted, training on current-strategy data only (300+ rows).
- Next: let it run untouched a few days; watch first retrain on new data.

## 2026-11-15
- Running, no errors in logs. Total 525 real trades (41% win), money $6,415 (start $7,271). 24h: -$59 ($6,474 -> $6,415).
- Last 50 trades (14.4h, so ~80/day): 16 wins / 34 losses (32%), avg win +3.1% vs avg loss -2.2%. 6 trades open.
- All 10 coins tend to win or lose together in the same hour (e.g. 10 losses at 02:00, 10 wins at 04:05), so each hour is really one bet repeated 10 times.
- Model retrained 10:00 on 757 current-strategy rows (524 real + 233 pretend). edge_found false; best holdout profit factor 0.97 (88 trades, threshold 0.7), baseline 0.61.
- Note: "Daily PnL" in logs is a sum of per-trade % returns, not account change (cosmetic; limit is 1.0 so it never blocks trades).
- Change: none. Last change was 2026-11-13 (<3 days) and nothing is broken. Committed this log locally only (no push, to avoid a restart).
- Next: watch whether profit factor keeps climbing toward 1.0+ as data grows; consider grouping same-hour coin trades in analysis.

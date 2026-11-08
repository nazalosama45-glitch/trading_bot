from bot import config
from bot.data_feed import get_exchange

print("testnet:", config.USE_TESTNET, "| dry_run:", config.DRY_RUN)
ex = get_exchange()
try:
    bal = ex.fetch_balance()["total"]
    print("CONNECTED. Test balances:", {k: v for k, v in bal.items() if v})
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:200])

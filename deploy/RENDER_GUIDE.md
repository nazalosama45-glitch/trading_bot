# Run the bot free on Render (with a pinger so it never sleeps)

Free but fragile. Render's free machine is small (512 MB memory, slow CPU), it can restart at
any time, and it sleeps unless something visits it every few minutes. The bot saves its
files into a free outside database so restarts don't erase its memory.

## A. Free database for the bot's memory (Neon)
1. Create a free account at neon.com (sign in with GitHub).
2. Create a project (any name, pick a Europe region).
3. Copy the **connection string** (starts with `postgresql://`). Keep it private: it is a password.

## B. Copy the bot's current memory to the database (optional but recommended)
First turn the bot **off** on your PC (dashboard, "Turn off"). Then in PowerShell, in the bot folder:
```
$env:DATABASE_URL = "PASTE_THE_CONNECTION_STRING"
python -m bot.persist push
Remove-Item Env:DATABASE_URL
```
It should say `Uploaded 3 files.`

## C. Put the code on GitHub (private repository)
1. On github.com create a **Private** repository named `trading-bot` (empty).
2. In PowerShell, in the bot folder:
```
git init
git add .
git commit -m "trading bot"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/trading-bot.git
git push -u origin main
```
`.gitignore` keeps your keys (`.env`), logs and data out of GitHub.

## D. Create the service on Render
1. Sign in at render.com with GitHub and allow it to see the `trading-bot` repository.
2. **New, then Blueprint**, pick the repository. Render reads `render.yaml`.
3. It asks for four secrets. Type them there (never anywhere else):
   - `DASHBOARD_PASSWORD`: a long password you invent (it protects the dashboard)
   - `DATABASE_URL`: the Neon connection string
   - `BINANCE_API_KEY` and `BINANCE_SECRET`: your **testnet** keys
4. Create it. Wait until the log shows `Dashboard running`.
5. Your address looks like `https://practice-trading-bot.onrender.com`. Open it and log in with
   user `admin` and your password.

## E. Keep it awake
1. Create a free account at uptimerobot.com.
2. Add a monitor: type **HTTP(s)**, URL `https://YOUR-NAME.onrender.com/healthz`, every **5 minutes**.

## Check it works
- The dashboard opens and shows "The bot is working".
- Render, Logs tab: no red `Cannot reach the state database` line.
- In Render, Manual Deploy, Restart service: after it comes back your open trades are still listed.

## Warnings
- Never run the bot on your PC and on Render at the same time (they would trade the same account twice).
- If the log says `Out of memory`, the free machine is too small: use the $5 server instead.
- This is testnet only. Practice mode refuses to run on real keys.

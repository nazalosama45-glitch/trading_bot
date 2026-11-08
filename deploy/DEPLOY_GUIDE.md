# Put the bot on a server (runs 24/7, your PC can be off)

Cost: about $4-6 per month. You do steps 1-4 once. About 20 minutes.

## 1. Rent a small server
- At any provider (Hetzner, DigitalOcean, Vultr, Contabo...) create a **Linux server**:
  - Image: **Ubuntu 24.04** (or 22.04)
  - Size: the smallest/cheapest (1 CPU, 1-2 GB RAM is enough)
  - Location: **not the USA** (Binance blocks US addresses; matters for real money later)
  - Login: password or SSH key, whichever the provider offers
- Write down the server's **IP address** (like `203.0.113.10`).

## 2. Stop the bot on your PC (important)
If your PC bot and the server bot run at the same time, they both trade the same
account and double up. Press **Turn off** on your local dashboard first, then:

## 3. Send the files to the server (PowerShell, in the `trading bot` folder)
```
python make_deploy_zip.py
scp trading-bot.zip deploy/setup_server.sh root@YOUR_SERVER_IP:/root/
```
(`scp` asks for the server password. The zip never contains your keys.)

## 4. Install and start (one command)
```
ssh root@YOUR_SERVER_IP
bash setup_server.sh
```
It asks you to paste your **testnet** API key and secret (hidden while typing), installs
everything, and starts the bot as a service. Then type `exit`.

## 5. Watch the dashboard from your PC
The dashboard is **not** open to the internet (that's on purpose). Open a private tunnel:
```
ssh -L 5001:localhost:5000 root@YOUR_SERVER_IP
```
Leave that window open and visit **http://localhost:5001** in your browser.
Close the window and the tunnel closes; the bot keeps running on the server.

## If you use Oracle Cloud's free tier
- Logging in is with a **key file** (downloaded when you create the server) and the user is
  **ubuntu**, not root. Replace the commands above with:
  ```
  scp -i C:\path\to\your.key trading-bot.zip deploy/setup_server.sh ubuntu@YOUR_SERVER_IP:/home/ubuntu/
  ssh -i C:\path\to\your.key ubuntu@YOUR_SERVER_IP
  sudo bash setup_server.sh
  ```
  and the tunnel: `ssh -i C:\path\to\your.key -L 5001:localhost:5000 ubuntu@YOUR_SERVER_IP`
- Pick your home region carefully at sign-up (it can't be changed). Not the USA.
- Free servers can be reclaimed if Oracle thinks they sit idle. If the bot ever vanishes, rerun the steps.

## Useful commands (on the server, after `ssh root@YOUR_SERVER_IP`)
| What | Command |
|---|---|
| Is it running? | `systemctl status trading-bot` |
| Recent log | `journalctl -u trading-bot -n 50 --no-pager` |
| Turn it off | `systemctl stop trading-bot` |
| Turn it on | `systemctl start trading-bot` |

## Safety notes
- It restarts itself after a crash or server reboot.
- It only trades the Binance **testnet** (fake money). Practice mode refuses to run on real keys.
- Never type your real Binance keys into this setup. Real money is a separate decision for later.
- Only the SSH port is reachable from outside, so the dashboard can't be used by strangers.

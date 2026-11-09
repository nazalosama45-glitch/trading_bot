"""
Flask dashboard: live stats, trade history, start/stop bot control.
Run with: python dashboard/server.py
Then open: http://localhost:5000
"""
import sys
import os
import hmac
import json
import sqlite3
import subprocess
import signal
import threading
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_from_directory

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

app = Flask(__name__, static_folder="static")

DB_PATH = Path("data/trades.db")
BOT_PROCESS: subprocess.Popen | None = None
BOT_LOCK = threading.Lock()

# Safe by default: only reachable from this computer. On a server, keep it that way and
# open it through an SSH tunnel, or set DASHBOARD_PASSWORD before changing DASHBOARD_HOST.
DASH_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASH_PORT = int(os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or "5000")  # hosts like Render set PORT
DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
AUTOSTART_BOT = os.getenv("AUTOSTART_BOT", "false").lower() == "true"
# When true, viewing needs no login; only the actions that change things (start/stop) still do.
PUBLIC_READ = os.getenv("DASHBOARD_PUBLIC_READ", "false").lower() == "true"
PUBLIC_CONTROL = os.getenv("DASHBOARD_PUBLIC_CONTROL", "false").lower() == "true"
WANT_RUNNING = False  # True once the bot has been started; the watchdog restarts it if it dies


@app.route("/healthz")
def healthz():
    return "ok"  # open on purpose: a pinger hits this to keep a free host awake; it reveals nothing


@app.before_request
def require_login():
    if not DASH_PASSWORD or request.path == "/healthz":
        return None
    if PUBLIC_READ and request.method in ("GET", "HEAD"):
        return None
    if PUBLIC_CONTROL and request.path in ("/api/bot/start", "/api/bot/stop"):
        return None
    auth = request.authorization
    if (auth
            and hmac.compare_digest(auth.username.encode(), DASH_USER.encode())
            and hmac.compare_digest((auth.password or "").encode(), DASH_PASSWORD.encode())):
        return None
    return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Trading bot"'})


def _start_bot_locked():
    global BOT_PROCESS
    Path(__file__).parent.parent.joinpath("logs").mkdir(exist_ok=True)
    BOT_PROCESS = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=Path(__file__).parent.parent,
    )


def _watchdog():
    while True:
        time.sleep(15)
        with BOT_LOCK:
            if WANT_RUNNING and (BOT_PROCESS is None or BOT_PROCESS.poll() is not None):
                try:
                    _start_bot_locked()
                    print("Watchdog: bot had stopped, restarted it", flush=True)
                except Exception as e:
                    print(f"Watchdog: restart failed: {e}", flush=True)


def _db():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH)


# ── API routes ─────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def stats():
    con = _db()
    if not con:
        return jsonify({"error": "No trade data yet"})
    try:
        rows = con.execute(
            "SELECT pnl, profitable, symbol, side, entry, exit_price, ts, COALESCE(pnl_usd, 0) FROM trades "
            "WHERE source = 'live' ORDER BY id DESC"
        ).fetchall()
        con.close()
    except Exception:
        return jsonify({"error": "Database not ready"})

    if not rows:
        return jsonify({"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_usd": 0,
                        "total_pnl": 0, "best_trade": 0, "worst_trade": 0, "trades": []})

    wins = sum(r[1] for r in rows)
    total = len(rows)

    # Convert raw price PnL to percentage return
    def to_pct(pnl, entry):
        if entry and entry > 0:
            return round(pnl / entry * 100, 2)
        return 0.0

    pnl_pcts = [to_pct(r[0], r[4]) for r in rows]

    trades_list = [
        {
            "ts": r[6],
            "symbol": r[2],
            "side": r[3],
            "entry": r[4],
            "exit": r[5],
            "pnl": to_pct(r[0], r[4]),
            "win": bool(r[1]),
        }
        for r in rows[:50]
    ]

    return jsonify({
        "total": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "total_pnl": round(sum(pnl_pcts), 2),
        "total_usd": round(sum(r[7] for r in rows), 2),
        "best_trade": round(max(pnl_pcts), 2),
        "worst_trade": round(min(pnl_pcts), 2),
        "trades": trades_list,
    })


@app.route("/api/bot/status")
def bot_status():
    with BOT_LOCK:
        running = BOT_PROCESS is not None and BOT_PROCESS.poll() is None
    return jsonify({"running": running})


@app.route("/api/bot/start", methods=["POST"])
def bot_start():
    global WANT_RUNNING
    with BOT_LOCK:
        if BOT_PROCESS and BOT_PROCESS.poll() is None:
            return jsonify({"ok": False, "msg": "Already running"})
        try:
            _start_bot_locked()
            WANT_RUNNING = True
            return jsonify({"ok": True, "msg": "Bot started"})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    global BOT_PROCESS, WANT_RUNNING
    with BOT_LOCK:
        WANT_RUNNING = False
        if not BOT_PROCESS or BOT_PROCESS.poll() is not None:
            return jsonify({"ok": False, "msg": "Bot is not running"})
        BOT_PROCESS.send_signal(signal.SIGTERM)
        BOT_PROCESS.wait(timeout=10)
        BOT_PROCESS = None
    return jsonify({"ok": True, "msg": "Bot stopped"})


@app.route("/api/positions")
def positions():
    f = Path("data/positions.json")
    if not f.exists():
        return jsonify({"updated": None, "positions": []})
    try:
        return jsonify(json.loads(f.read_text()))
    except (OSError, ValueError):
        return jsonify({"updated": None, "positions": []})


@app.route("/api/equity")
def equity_history():
    try:
        return jsonify({"points": json.loads(Path("data/equity.json").read_text())})
    except (OSError, ValueError):
        return jsonify({"points": []})


@app.route("/api/learning")
def learning():
    from bot import learner
    return jsonify({"sources": learner.source_counts(), "report": learner.load_learning() or {}})


@app.route("/api/logs")
def logs():
    log_file = Path("logs/bot.log")
    if not log_file.exists():
        return jsonify({"lines": []})
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip()[:200] for l in lines[-600:]]})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    static = Path(__file__).parent / "static"
    if path and (static / path).exists():
        return send_from_directory(str(static), path)
    return send_from_directory(str(static), "index.html")


if __name__ == "__main__":
    from bot import learner, persist

    if DASH_HOST != "127.0.0.1" and not DASH_PASSWORD:
        sys.exit("Refusing to start: DASHBOARD_HOST is open to the network but DASHBOARD_PASSWORD is empty.")

    if persist.enabled():
        try:
            n = persist.restore()
            print(f"Restored {n} saved file(s) from the database", flush=True)
        except Exception as e:
            # Starting empty and then backing up would overwrite the saved copy, so stop instead.
            sys.exit(f"Cannot reach the state database ({e}). Not starting, to protect saved data.")
        threading.Thread(target=persist.sync_loop, daemon=True).start()

        def _shutdown(signum, frame):
            global WANT_RUNNING
            WANT_RUNNING = False
            with BOT_LOCK:
                if BOT_PROCESS and BOT_PROCESS.poll() is None:
                    BOT_PROCESS.terminate()
                    try:
                        BOT_PROCESS.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        BOT_PROCESS.kill()
            try:
                persist.upload_all()
            except Exception as e:
                print(f"Final backup failed: {e}", flush=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)

    learner.init_db()
    if os.getenv("RESET_ON_START", "false").lower() == "true":
        con = _db()
        if con:
            con.execute("DELETE FROM trades WHERE source IN ('live', 'shadow')")
            con.commit()
            con.close()
        pos_file = Path("data/positions.json")
        if pos_file.exists():
            pos_file.write_text(json.dumps({"updated": None, "positions": []}))
        model_file = Path("models/model.pkl")
        if model_file.exists():
            try:
                model_file.unlink()
            except OSError:
                pass
        print("RESET_ON_START: cleared live/shadow trades and positions.", flush=True)
    if AUTOSTART_BOT:
        with BOT_LOCK:
            _start_bot_locked()
            WANT_RUNNING = True
    threading.Thread(target=_watchdog, daemon=True).start()
    print(f"Dashboard running at http://{DASH_HOST}:{DASH_PORT}", flush=True)
    app.run(host=DASH_HOST, port=DASH_PORT, debug=False)

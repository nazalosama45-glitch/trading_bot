"""
Keeps the bot's saved files alive on hosts that erase the disk on every restart
(for example Render's free tier). Active only when DATABASE_URL is set.

The three state files are stored as blobs in one Postgres table:
restore() runs before the bot starts, a background loop uploads changes, and a final
upload runs on shutdown.

    python -m bot.persist push   # upload this computer's current state (seed the cloud copy)
    python -m bot.persist pull   # download the cloud copy into this folder
"""
import hashlib
import logging
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger("persist")

# Only these files are ever written back, so a bad database row can't touch other paths.
FILES = ["data/trades.db", "data/positions.json", "data/equity.json", "models/model.pkl", "models/learning.json"]

_last_digest: dict = {}


def enabled() -> bool:
    return bool(os.getenv("DATABASE_URL"))


def _connect():
    import psycopg2

    con = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=15)
    with con.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS bot_files ("
            "name TEXT PRIMARY KEY, data BYTEA NOT NULL, updated TIMESTAMPTZ DEFAULT now())"
        )
    con.commit()
    return con


def _save(con, name: str, data: bytes):
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_files (name, data, updated) VALUES (%s, %s, now()) "
            "ON CONFLICT (name) DO UPDATE SET data = EXCLUDED.data, updated = now()",
            (name, data),
        )
    con.commit()


def _load_all(con) -> list:
    with con.cursor() as cur:
        cur.execute("SELECT name, data FROM bot_files")
        return [(name, bytes(data)) for name, data in cur.fetchall()]


def _snapshot(name: str):
    path = Path(name)
    if not path.exists():
        return None
    if name.endswith(".db"):
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        src = sqlite3.connect(path)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)  # consistent copy even while the bot is writing
        finally:
            src.close()
            dst.close()
        data = Path(tmp).read_bytes()
        os.remove(tmp)
        return data
    return path.read_bytes()


def restore() -> int:
    """Copy saved files from the database to disk. Raises if the database can't be reached."""
    if not enabled():
        return 0
    con = _connect()
    try:
        restored = 0
        for name, data in _load_all(con):
            if name not in FILES:
                continue
            path = Path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            _last_digest[name] = hashlib.sha1(data).hexdigest()
            restored += 1
            logger.info(f"Restored {name} ({len(data) / 1024:.0f} KB)")
        return restored
    finally:
        con.close()


def upload_all(force: bool = False) -> int:
    """Upload the state files that changed since the last upload. Returns how many were sent."""
    if not enabled():
        return 0
    con = _connect()
    try:
        sent = 0
        for name in FILES:
            data = _snapshot(name)
            if data is None:
                continue
            digest = hashlib.sha1(data).hexdigest()
            if not force and _last_digest.get(name) == digest:
                continue
            _save(con, name, data)
            _last_digest[name] = digest
            sent += 1
        return sent
    finally:
        con.close()


def sync_loop(interval: int = 60):
    while True:
        time.sleep(interval)
        try:
            upload_all()
        except Exception as e:
            logger.warning(f"State backup failed (will retry): {e}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not enabled():
        sys.exit("Set DATABASE_URL first (in .env or the environment).")
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "push":
        print(f"Uploaded {upload_all(force=True)} files.")
    elif action == "pull":
        print(f"Downloaded {restore()} files.")
    else:
        sys.exit("Usage: python -m bot.persist push|pull")

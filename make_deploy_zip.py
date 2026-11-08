"""Packs the bot into trading-bot.zip for the server. Never includes .env (your keys) or logs."""
import zipfile
from pathlib import Path

root = Path(__file__).parent
out = root / "trading-bot.zip"
skip_dirs = {"__pycache__", "logs", "venv", ".git"}

count = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if p.name == ".env" or p.suffix in {".zip", ".pyc"} or p.name.endswith(".tmp"):
            continue
        z.write(p, rel.as_posix())
        count += 1

print(f"Wrote {out.name}: {count} files, {out.stat().st_size / 1024:.0f} KB (no .env, no logs)")

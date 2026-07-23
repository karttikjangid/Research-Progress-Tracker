"""The survive-180-days layer: paths, logging, migrations, backups.

Everything stateful lives under STATE_ROOT (repo root by default,
GATEKEEPER_STATE overrides — tests point it at a temp dir).
"""
import logging
import os
import shutil
import sqlite3
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = Path(os.getenv("GATEKEEPER_STATE", str(ROOT)))
DATA_DIR = STATE_ROOT / "data"
BACKUP_DIR = STATE_ROOT / "backups"
LOG_DIR = STATE_ROOT / "logs"
PUBLIC_LOG = STATE_ROOT / "public_log.md"
MIGRATIONS = Path(__file__).resolve().parent / "migrations"
KEEP_BACKUPS = 14

for _d in (DATA_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("gatekeeper")
if not log.handlers:
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    _h = TimedRotatingFileHandler(LOG_DIR / "gatekeeper.log",
                                  when="midnight", backupCount=14)
    _h.setFormatter(_fmt)
    log.addHandler(_h)
    # Render (and most container hosts) only capture stdout/stderr — the file
    # handler above writes to STATE_ROOT/logs, which on the free plan is
    # ephemeral disk that isn't shown anywhere. Without this, every log.error /
    # log.exception call (e.g. "recording N: audit failed: ...") is invisible
    # in the hosting dashboard. Explicit stdout, not StreamHandler()'s stderr
    # default — most log dashboards (Render included) flag stderr lines as
    # errors, which would paint every plain log.info() red.
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    log.addHandler(_sh)
    log.setLevel(logging.INFO)


def migrate(engine):
    """Apply numbered migrations/NNN_*.sql not yet in schema_version.

    Runs each file through sqlite3.executescript (not a naive split on ';'),
    which parses whole scripts including CREATE TRIGGER … BEGIN … END; blocks
    whose bodies contain semicolons. Uses a short-lived raw connection at import
    time, before the app opens any BEGIN IMMEDIATE transaction, so there is no
    lock contention with the engine.
    """
    path = engine.url.database
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        current = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        for f in sorted(MIGRATIONS.glob("[0-9]*.sql")):
            v = int(f.name.split("_", 1)[0])
            if v <= current:
                continue
            conn.executescript(f.read_text())
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (v,))
            conn.commit()
            log.info("migration %s applied", f.name)
    finally:
        conn.close()


def backup(db_path: str, date: str) -> bool:
    """Copy DB (via sqlite backup API — WAL-safe) + the day's audio into
    backups/<date>/, prune to the newest KEEP_BACKUPS. Never raises."""
    try:
        dest = BACKUP_DIR / date
        dest.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(dest / "gatekeeper.db")
            with dst:
                src.backup(dst)
            dst.close()
        finally:
            src.close()
        audio = DATA_DIR / "audio" / date
        if audio.is_dir():
            shutil.copytree(audio, dest / "audio", dirs_exist_ok=True)
        dated = sorted(d for d in BACKUP_DIR.iterdir() if d.is_dir())
        for old in dated[:-KEEP_BACKUPS]:
            shutil.rmtree(old)
        log.info("backup written: %s", dest)
        return True
    except Exception:
        log.exception("BACKUP FAILED for %s — fix before trusting the system", date)
        return False

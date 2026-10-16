"""Small durable SQLite queue for private source CSV exports."""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    connection.execute("""CREATE TABLE IF NOT EXISTS exports (
        sha256 TEXT PRIMARY KEY, created_at TEXT NOT NULL, csv BLOB,
        uploaded_at TEXT)""")
    connection.commit()
    return connection


def enqueue(path: Path, csv_bytes: bytes) -> str:
    digest = hashlib.sha256(csv_bytes).hexdigest()
    with connect(path) as db:
        db.execute("INSERT OR IGNORE INTO exports(sha256, created_at, csv) VALUES (?, ?, ?)",
                   (digest, datetime.now(timezone.utc).isoformat(), csv_bytes))
    return digest


def pending(path: Path):
    with connect(path) as db:
        return db.execute("SELECT sha256, csv FROM exports WHERE uploaded_at IS NULL ORDER BY created_at, sha256").fetchall()


def acknowledge(path: Path, digest: str) -> None:
    with connect(path) as db:
        db.execute("UPDATE exports SET uploaded_at = ?, csv = NULL WHERE sha256 = ?",
                   (datetime.now(timezone.utc).isoformat(), digest))

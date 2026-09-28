"""Koneksi SQLite + pembungkus run_log (jejak eksekusi)."""

import sqlite3
from datetime import datetime

from . import config


def now() -> str:
    return datetime.now(config.WIB).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(config.WIB).date().isoformat()


def sym(s) -> str:
    """Normalisasi ticker: 'BBCA.JK' -> 'BBCA'."""
    return (s or "").replace(".JK", "").strip().upper()


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | None = None) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


class Run:
    """Satu baris run_log per job. Ini jejak audit eksekusi terjadwal."""

    def __init__(self, conn, client, job: str, trigger: str = "manual"):
        self.conn, self.client, self.job, self.trigger = conn, client, job, trigger
        self.rows = 0
        self.run_id = None

    def __enter__(self):
        cur = self.conn.execute(
            "INSERT INTO run_log(job,trigger,started_at,status) VALUES (?,?,?,'running')",
            (self.job, self.trigger, now()),
        )
        self.conn.commit()
        self.run_id = cur.lastrowid
        if self.client is not None:
            self.client.run_id = self.run_id
            self.client.credits = 0
        print(f"\n=== {self.job}  (run {self.run_id}, {self.trigger}) ===")
        return self

    def __exit__(self, exc_type, exc, tb):
        credits = getattr(self.client, "credits", 0) if self.client else 0
        status = "ok" if exc is None else "error"
        self.conn.execute(
            "UPDATE run_log SET finished_at=?,status=?,rows_written=?,credits=?,error=? "
            "WHERE run_id=?",
            (now(), status, self.rows, credits,
             None if exc is None else repr(exc)[:500], self.run_id),
        )
        self.conn.commit()
        print(f"--- {self.job}: {status} | {self.rows} baris | {credits} kredit")
        return False

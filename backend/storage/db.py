"""SQLite connection manager and schema."""
import sqlite3
import threading
from pathlib import Path

from backend.config import DATA_DIR

DB_PATH = DATA_DIR / "trading.db"

_local = threading.local()

def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn

def init_schema():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT,
            list_date TEXT CHECK (list_date IS NULL OR list_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
            is_active INTEGER DEFAULT 1,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS download_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            data_type TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            rows_count INTEGER,
            error_msg TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_download_log_symbol ON download_log(symbol);
        CREATE INDEX IF NOT EXISTS idx_download_log_created ON download_log(created_at);

        CREATE TABLE IF NOT EXISTS backtest_results (
            id TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            params TEXT,
            start_date TEXT,
            end_date TEXT,
            universe TEXT,
            metrics TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_name);
        CREATE INDEX IF NOT EXISTS idx_backtest_created ON backtest_results(created_at);
    """)
    conn.commit()

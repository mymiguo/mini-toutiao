"""Data service orchestrating fetch → clean → store → query."""
import asyncio
import uuid
from datetime import datetime, date
from typing import Optional

import pandas as pd
from loguru import logger

from backend.storage.fetcher import fetch_daily, fetch_stock_list, fetch_financials
from backend.storage.cleaner import clean_daily, save_cleaned, load_cleaned, load_bulk, get_latest_date
from backend.storage.db import get_conn

_download_tasks: dict[str, dict] = {}

async def download_daily(symbols: list[str], start_date: str, end_date: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    _download_tasks[task_id] = {"status": "running", "done": 0, "total": len(symbols), "errors": []}
    errors = []

    async def _dl_one(symbol: str):
        try:
            latest = get_latest_date(symbol)
            actual_start = start_date
            if latest and latest >= start_date:
                actual_start = str(pd.Timestamp(latest) + pd.Timedelta(days=1))
            if actual_start > end_date:
                logger.info(f"{symbol} is up to date, skipping")
                return
            df = await fetch_daily(symbol, actual_start, end_date)
            if df is not None and not df.empty:
                cleaned = clean_daily(df)
                if not cleaned.empty:
                    save_cleaned(cleaned, symbol)
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
            logger.error(f"Download failed for {symbol}: {e}")
        finally:
            _download_tasks[task_id]["done"] += 1

    sem = asyncio.Semaphore(3)
    await asyncio.gather(*[_dl_one(s) for s in symbols])
    _download_tasks[task_id]["status"] = "completed"
    _download_tasks[task_id]["errors"] = errors
    return task_id

def get_download_status(task_id: str) -> dict:
    return _download_tasks.get(task_id, {"status": "not_found"})

def get_stock_list() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT symbol, name, industry FROM stocks WHERE is_active=1").fetchall()
    return [dict(r) for r in rows]

def refresh_stock_list() -> int:
    df = asyncio.run(fetch_stock_list())
    if df.empty:
        return 0
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        conn.execute(
            "INSERT OR REPLACE INTO stocks (symbol, name, updated_at) VALUES (?, ?, ?)",
            (str(row["code"]), str(row["name"]), datetime.now().isoformat())
        )
        count += 1
    conn.commit()
    return count

def get_daily(symbol: str, start: str = None, end: str = None) -> list[dict]:
    df = load_cleaned(symbol, start, end)
    return df.to_dict(orient="records")

def get_financials(symbol: str) -> dict:
    return asyncio.run(fetch_financials(symbol))

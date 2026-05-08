# A股自动化交易工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python FastAPI + Electron A-share desktop trading tool with data pipeline, strategy engine, backtesting, optimization, and sentiment analysis.

**Architecture:** FastAPI backend serves REST API on localhost:8765; Electron frontend communicates via HTTP. Data flows: AKShare/BaoStock → fetcher → cleaner → Parquet/SQLite → services → API → frontend.

**Tech Stack:** Python 3.11, FastAPI, pandas, numpy, AKShare, BaoStock, SQLite, Parquet (pyarrow), Optuna, loguru

---

## File Map

| File | Responsibility |
|------|---------------|
| `backend/config.py` | Load config.yaml, expose settings object |
| `backend/main.py` | FastAPI app, startup/shutdown lifecycle, CORS |
| `backend/models.py` | Pydantic models shared across API routes |
| `backend/storage/db.py` | SQLite connection, schema init, metadata CRUD |
| `backend/storage/fetcher.py` | AKShare/BaoStock download with fallback and rate limit |
| `backend/storage/cleaner.py` | Dedup, adjust, validate OHLCV data |
| `backend/services/data_service.py` | Business logic orchestrating fetch→clean→store→read |
| `backend/api/data.py` | REST endpoints for data operations |
| `backend/engine/strategy.py` | BaseStrategy ABC, Signal dataclass |
| `backend/engine/indicators.py` | Technical indicator functions |
| `backend/engine/backtest.py` | BacktestEngine with T+1, fees, circuit breaker |
| `backend/services/strategy_service.py` | Strategy CRUD, template management |
| `backend/services/backtest_service.py` | Backtest job management, result storage |
| `backend/api/strategy.py` | Strategy REST endpoints |
| `backend/api/backtest.py` | Backtest REST endpoints |
| `backend/engine/optimizer.py` | Optuna-based parameter optimization |
| `backend/engine/sentiment.py` | 5-factor sentiment scoring |
| `backend/services/sentiment_service.py` | Sentiment data computation and caching |
| `backend/api/sentiment.py` | Sentiment REST endpoints |
| `backend/requirements.txt` | Python dependencies |
| `config.yaml` | Global configuration |

---

## Phase 1: 数据管线 (基础)

### Task 1: 项目骨架初始化

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/requirements.txt`
- Create: `backend/config.py`
- Create: `config.yaml`

- [ ] **Step 1: Create `config.yaml`**

```yaml
# A股交易工具全局配置
data:
  raw_dir: data/raw
  cleaned_dir: data/cleaned
  cache_dir: data/cache
  primary_source: akshare
  fallback_source: baostock
  rate_limit: 10
  rate_period: 1

server:
  host: 127.0.0.1
  port: 8765

logging:
  level: INFO
  retention: 30
```

- [ ] **Step 2: Create `backend/__init__.py`**

```python
"""A股自动化交易工具 backend."""
```

- [ ] **Step 3: Create `backend/config.py`**

```python
"""Load and expose YAML configuration."""
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)

DATA_DIR = Path(settings["data"]["raw_dir"])
CLEANED_DIR = Path(settings["data"]["cleaned_dir"])
CACHE_DIR = Path(settings["data"]["cache_dir"])

for d in (DATA_DIR, CLEANED_DIR, CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Create `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
pandas>=2.2.0
numpy>=1.26.0
akshare>=1.14.0
baostock>=0.8.8
pyarrow>=17.0.0
pyyaml>=6.0
loguru>=0.7.0
pydantic>=2.9.0
optuna>=3.6.0
```

- [ ] **Step 5: Install dependencies**

```bash
cd backend && pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 6: Commit**

```bash
git add config.yaml backend/
git commit -m "feat: project skeleton with config and dependencies"
```

---

### Task 2: SQLite 存储层

**Files:**
- Create: `backend/storage/__init__.py`
- Create: `backend/storage/db.py`

- [ ] **Step 1: Write `backend/storage/__init__.py`**

```python
"""Data storage layer."""
```

- [ ] **Step 2: Write `backend/storage/db.py`**

```python
"""SQLite connection manager and schema."""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "trading.db"

_local = threading.local()

def get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn

def init_schema():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT,
            list_date TEXT,
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
    """)
    conn.commit()
```

- [ ] **Step 3: Verify schema creation**

```bash
python -c "from backend.storage.db import init_schema; init_schema(); print('Schema OK')"
```

Expected: `Schema OK`, `data/trading.db` file exists.

- [ ] **Step 4: Commit**

```bash
git add backend/storage/ data/
git commit -m "feat: SQLite storage layer with schema"
```

---

### Task 3: 数据下载模块 (fetcher)

**Files:**
- Create: `backend/storage/fetcher.py`

- [ ] **Step 1: Write `backend/storage/fetcher.py`**

```python
"""Data fetcher for AKShare (primary) with BaoStock fallback."""
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

from backend.config import settings as cfg

MAX_RETRIES = 3
BASE_DELAY = 1.0

async def _rate_limited_call(sem: asyncio.Semaphore, fn, *args, **kwargs):
    async with sem:
        for attempt in range(MAX_RETRIES):
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
                return result
            except Exception as e:
                delay = BASE_DELAY * (2 ** attempt)
                logger.warning(f"Attempt {attempt+1}/{MAX_RETRIES} failed: {e}, retry in {delay}s")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
        raise RuntimeError(f"All {MAX_RETRIES} attempts exhausted for {fn.__name__}")

async def fetch_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    sem = asyncio.Semaphore(cfg.get("rate_limit", 10))
    try:
        df = await _rate_limited_call(sem, _akshare_daily, symbol, start_date, end_date)
    except Exception:
        logger.info(f"AKShare failed for {symbol}, falling back to BaoStock")
        df = await _rate_limited_call(sem, _baostock_daily, symbol, start_date, end_date)
    if df.empty:
        return df
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
        "成交额": "amount", "换手率": "turnover"
    })
    keep_cols = ["date", "open", "high", "low", "close", "volume", "amount"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    for c in ["open", "high", "low", "close"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["symbol"] = symbol
    return df

def _akshare_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Use AKShare stock_zh_a_hist."""
    return ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        adjust="qfq"
    )

def _baostock_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """BaoStock fallback for daily K-line."""
    import baostock as bs
    bs.login()
    code = ("sh." if symbol.startswith("6") else "sz.") + symbol
    rs = bs.query_history_k_data_plus(
        code, "date,open,high,low,close,volume,amount",
        start_date=start, end_date=end, frequency="d",
        adjustflag="2"
    )
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    bs.logout()
    return pd.DataFrame(rows, columns=["date","open","high","low","close","volume","amount"])

async def fetch_stock_list() -> pd.DataFrame:
    sem = asyncio.Semaphore(cfg.get("rate_limit", 10))
    return await _rate_limited_call(sem, ak.stock_info_a_code_name)

async def fetch_financials(symbol: str) -> dict:
    sem = asyncio.Semaphore(cfg.get("rate_limit", 10))
    try:
        df = await _rate_limited_call(sem, ak.stock_financial_abstract_ths, symbol)
        return {"symbol": symbol, "data": df}
    except Exception as e:
        logger.error(f"Failed to fetch financials for {symbol}: {e}")
        return {"symbol": symbol, "data": pd.DataFrame(), "error": str(e)}

async def fetch_dragon_tiger(date: Optional[str] = None) -> pd.DataFrame:
    sem = asyncio.Semaphore(cfg.get("rate_limit", 10))
    d = date or datetime.now().strftime("%Y%m%d")
    return await _rate_limited_call(sem, ak.stock_lhb_detail_em, date=d)

async def fetch_money_flow(symbol: str) -> pd.DataFrame:
    sem = asyncio.Semaphore(cfg.get("rate_limit", 10))
    return await _rate_limited_call(sem, ak.stock_individual_fund_flow, stock=symbol, market="sh")
```

- [ ] **Step 2: Smoke test fetcher**

```bash
python -c "
import asyncio
from backend.storage.fetcher import fetch_stock_list
df = asyncio.run(fetch_stock_list())
print(f'Got {len(df)} stocks')
print(df.head(3))
"
```

Expected: prints stock count and first 3 rows.

- [ ] **Step 3: Commit**

```bash
git add backend/storage/fetcher.py
git commit -m "feat: AKShare fetcher with BaoStock fallback"
```

---

### Task 4: 数据清洗模块 (cleaner)

**Files:**
- Create: `backend/storage/cleaner.py`

- [ ] **Step 1: Write `backend/storage/cleaner.py`**

```python
"""Clean and validate OHLCV data before storage."""
import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger

from backend.config import DATA_DIR, CLEANED_DIR

def clean_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Clean daily OHLCV data: dedup, validate, mark suspensions."""
    if df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["symbol", "date"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        mask = (df["open"] == 0) & (df["high"] == 0) & (df["low"] == 0) & (df["close"] == 0)
        df.loc[mask, "is_suspended"] = 1
        df["is_suspended"] = df["is_suspended"].fillna(0).astype(int)
    return df

def save_cleaned(df: pd.DataFrame, symbol: str):
    """Save cleaned data as Parquet, partitioned by symbol."""
    out_dir = CLEANED_DIR / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol}.parquet"
    if path.exists():
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)
        df = df.drop_duplicates(subset=["symbol", "date"]).sort_values("date")
    df.to_parquet(path, index=False)
    logger.info(f"Saved {len(df)} rows for {symbol}")

def load_cleaned(symbol: str, start: str = None, end: str = None) -> pd.DataFrame:
    path = CLEANED_DIR / "daily" / f"{symbol}.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["date"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)

def get_latest_date(symbol: str) -> str | None:
    df = load_cleaned(symbol)
    if df.empty:
        return None
    return str(df["date"].max().date())

def load_bulk(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    frames = []
    for s in symbols:
        df = load_cleaned(s, start, end)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
```

- [ ] **Step 2: Verify cleaner with mock data**

```bash
python -c "
import pandas as pd
from backend.storage.cleaner import clean_daily, save_cleaned, load_cleaned

df = pd.DataFrame({
    'symbol': ['000001']*3,
    'date': ['2024-01-01','2024-01-02','2024-01-02'],
    'open': [10,11,11], 'high': [11,12,12],
    'low': [9,10,10], 'close': [10.5,11.5,11.5],
    'volume': [1e6,2e6,2e6]
})
cleaned = clean_daily(df)
print(f'Rows after dedup: {len(cleaned)}')
save_cleaned(cleaned, '000001')
loaded = load_cleaned('000001')
print(f'Loaded rows: {len(loaded)}')
"
```

Expected: dedup removes 1 duplicate, saves and loads correctly.

- [ ] **Step 4: Commit**

```bash
git add backend/storage/cleaner.py
git commit -m "feat: data cleaner with dedup, validation, Parquet storage"
```

---

### Task 5: 数据服务层 (data_service)

**Files:**
- Create: `backend/services/__init__.py`
- Create: `backend/services/data_service.py`

- [ ] **Step 1: Write `backend/services/__init__.py`**

```python
"""Business logic services."""
```

- [ ] **Step 2: Write `backend/services/data_service.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add backend/services/
git commit -m "feat: data service orchestrating download, clean, and query"
```

---

### Task 6: FastAPI 数据接口

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/data.py`
- Create: `backend/models.py`
- Create: `backend/main.py`

- [ ] **Step 1: Write `backend/api/__init__.py`**

```python
"""API route handlers."""
```

- [ ] **Step 2: Write `backend/models.py`**

```python
"""Shared Pydantic models."""
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    error: str
    detail: str

class DownloadRequest(BaseModel):
    symbols: list[str]
    start_date: str
    end_date: str

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    done: int
    total: int
    errors: list[dict]
```

- [ ] **Step 3: Write `backend/api/data.py`**

```python
"""Data REST API endpoints."""
from fastapi import APIRouter, HTTPException, Query

from backend.models import DownloadRequest, DownloadStatus
from backend.services.data_service import (
    download_daily,
    get_download_status,
    get_stock_list,
    refresh_stock_list,
    get_daily,
    get_financials,
)
from backend.storage.cleaner import get_latest_date

router = APIRouter(prefix="/api/data", tags=["data"])

@router.get("/stocks")
async def stocks():
    return get_stock_list()

@router.post("/stocks/refresh")
async def refresh():
    count = refresh_stock_list()
    return {"count": count}

@router.get("/daily/{symbol}")
async def daily(symbol: str, start: str = None, end: str = None):
    data = get_daily(symbol, start, end)
    return {"symbol": symbol, "count": len(data), "data": data}

@router.get("/latest/{symbol}")
async def latest_date(symbol: str):
    d = get_latest_date(symbol)
    return {"symbol": symbol, "latest_date": d}

@router.post("/download")
async def download(req: DownloadRequest):
    task_id = await download_daily(req.symbols, req.start_date, req.end_date)
    return {"task_id": task_id}

@router.get("/download/status/{task_id}")
async def download_status(task_id: str):
    return get_download_status(task_id)

@router.get("/financials/{symbol}")
async def financials(symbol: str):
    return get_financials(symbol)
```

- [ ] **Step 4: Write `backend/main.py`**

```python
"""FastAPI application entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.api.data import router as data_router
from backend.storage.db import init_schema

app = FastAPI(title="A股交易工具", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router)

@app.on_event("startup")
async def startup():
    init_schema()
    logger.info("Backend started on :8765")

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "detail": str(exc)}
    )

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
```

- [ ] **Step 5: Start backend and verify**

```bash
# Terminal 1: start server
cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8765 --reload &
sleep 3
curl http://127.0.0.1:8765/api/health
```

Expected: `{"status":"ok","version":"0.1.0"}`

- [ ] **Step 6: Test data endpoints**

```bash
curl http://127.0.0.1:8765/api/data/stocks/refresh
curl "http://127.0.0.1:8765/api/data/daily/000001?start=2024-01-01&end=2024-01-10"
```

Expected: first returns stock count, second returns daily data for 000001.

- [ ] **Step 7: Commit**

```bash
git add backend/api/ backend/models.py backend/main.py
git commit -m "feat: FastAPI entry point with data endpoints"
```

---

## Phase 2: 策略引擎 + 回测引擎

### Task 7: 策略基类 & 指标库

**Files:**
- Create: `backend/engine/__init__.py`
- Create: `backend/engine/strategy.py`
- Create: `backend/engine/indicators.py`

- [ ] **Step 1: Write `backend/engine/__init__.py`**

```python
"""Core trading engine components."""
```

- [ ] **Step 2: Write `backend/engine/strategy.py`**

```python
"""Base strategy class and Signal definition."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd


@dataclass
class Signal:
    symbol: str
    action: Literal["BUY", "SELL"]
    size: float
    price_type: Literal["open", "close", "limit"] = "close"
    limit_price: Optional[float] = None


class Portfolio:
    """Tracks current positions and cash during backtest."""
    def __init__(self, initial_cash: float = 100_000):
        self.cash = initial_cash
        self.positions: dict[str, dict] = {}
        self.pending_buys: list[Signal] = []

    def can_sell(self, symbol: str) -> bool:
        pos = self.positions.get(symbol)
        return pos is not None and pos["shares"] > 0 and pos["hold_days"] > 0

    def add_position(self, symbol: str, shares: int, price: float, date: str):
        self.positions[symbol] = {"shares": shares, "avg_cost": price, "date": date, "hold_days": 0}
        self.cash -= shares * price

    def close_position(self, symbol: str, price: float, shares: int = None):
        pos = self.positions[symbol]
        sold = shares or pos["shares"]
        self.cash += sold * price
        if shares is None or shares >= pos["shares"]:
            del self.positions[symbol]
        else:
            pos["shares"] -= shares

    def age_positions(self):
        for p in self.positions.values():
            p["hold_days"] += 1

    def equity(self, prices: dict[str, float]) -> float:
        pos_value = sum(
            self.positions[s]["shares"] * prices.get(s, 0)
            for s in self.positions
        )
        return self.cash + pos_value


class BaseStrategy(ABC):
    """Strategy base class. Subclass and implement init() and next()."""

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.portfolio: Optional[Portfolio] = None
        self.data: Optional[pd.DataFrame] = None
        self.indicators: dict = {}

    @abstractmethod
    def init(self):
        """Calculate indicators once. self.data is available."""
        ...

    @abstractmethod
    def next(self, i: int) -> Optional[Signal]:
        """Called on each bar. Return Signal or None."""
        ...
```

- [ ] **Step 3: Write `backend/engine/indicators.py`**

```python
"""Technical indicator functions. All operate on pandas Series."""
import pandas as pd
import numpy as np


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def macd(close: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    hist = 2 * (dif - dea)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist})

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def bollinger(close: pd.Series, period=20, std=2) -> pd.DataFrame:
    mid = sma(close, period)
    std_dev = close.rolling(period).std()
    upper = mid + std * std_dev
    lower = mid - std * std_dev
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period=14) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def volume_profile(volume: pd.Series, close: pd.Series, bins=10) -> dict:
    if close.empty:
        return {}
    price_range = np.linspace(close.min(), close.max(), bins + 1)
    labels = [f"{price_range[i]:.2f}-{price_range[i+1]:.2f}" for i in range(bins)]
    vol_dist = [0] * bins
    for i, price in enumerate(close):
        for j in range(bins):
            if price_range[j] <= price < price_range[j+1]:
                vol_dist[j] += volume.iloc[i]
                break
    return dict(zip(labels, vol_dist))

def cross_over(a: pd.Series, b: pd.Series, i: int) -> bool:
    if i < 1:
        return False
    return a.iloc[i] > b.iloc[i] and a.iloc[i-1] <= b.iloc[i-1]

def cross_under(a: pd.Series, b: pd.Series, i: int) -> bool:
    if i < 1:
        return False
    return a.iloc[i] < b.iloc[i] and a.iloc[i-1] >= b.iloc[i-1]
```

- [ ] **Step 4: Verify indicators**

```bash
python -c "
import pandas as pd
from backend.engine.indicators import sma, macd, rsi, cross_over

df = pd.DataFrame({'close': [10,11,12,11,10,9,10,11,12,13,12,11] + list(range(13,30))})
print('SMA 5:', sma(df['close'], 5).iloc[-1])
m = macd(df['close'])
print('MACD dif last:', m['dif'].iloc[-1])
print('RSI 14 last:', rsi(df['close'], 14).iloc[-1])
print('Cross check:', cross_over(df['close'], sma(df['close'], 5), 5))
"
```

Expected: numerical outputs for each indicator.

- [ ] **Step 5: Commit**

```bash
git add backend/engine/
git commit -m "feat: strategy base class and technical indicators"
```

---

### Task 8: 回测引擎

**Files:**
- Create: `backend/engine/backtest.py`

- [ ] **Step 1: Write `backend/engine/backtest.py`**

```python
"""Backtest engine with T+1, fees, and circuit breaker simulation."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Type

import numpy as np
import pandas as pd
from loguru import logger

from backend.engine.strategy import BaseStrategy, Portfolio, Signal
from backend.storage.cleaner import load_bulk


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    id: str
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trades: list[Trade]
    daily_equity: list[dict]
    benchmark_compare: dict


class BacktestEngine:
    """Run strategy backtest on historical data."""

    COMMISSION_RATE = 0.00025
    STAMP_TAX_RATE = 0.001
    SLIPPAGE = 0.0001

    def run(
        self,
        strategy_cls: Type[BaseStrategy],
        start_date: str,
        end_date: str,
        universe: list[str],
        initial_cash: float = 100_000,
        benchmark: str = "000300",
        params: dict = None,
    ) -> BacktestResult:
        df = load_bulk(universe, start_date, end_date)
        if df.empty:
            raise ValueError("No data for the given universe and date range")

        strategy = strategy_cls(params=params)
        strategy.data = df
        strategy.portfolio = Portfolio(initial_cash)
        strategy.init()

        trades: list[Trade] = []
        open_trades: dict[str, dict] = {}
        equity_curve: list[dict] = []
        dates = sorted(df["date"].unique())

        prev_equity = initial_cash
        peak_equity = initial_cash
        max_dd = 0.0

        daily_data = {d: df[df["date"] == d] for d in dates}

        for i, dt in enumerate(dates):
            bars = daily_data[dt]
            prices = dict(zip(bars["symbol"], bars["close"]))
            highs = dict(zip(bars["symbol"], bars["high"]))
            lows = dict(zip(bars["symbol"], bars["low"]))

            signal = strategy.next(i)
            if signal:
                self._execute(signal, bars, strategy.portfolio, open_trades, trades, dt)

            strategy.portfolio.age_positions()
            equity = strategy.portfolio.equity(prices)
            daily_returns = (equity - prev_equity) / prev_equity if prev_equity else 0
            prev_equity = equity
            peak_equity = max(peak_equity, equity)
            dd = (peak_equity - equity) / peak_equity
            max_dd = max(max_dd, dd)

            equity_curve.append({
                "date": str(dt)[:10], "equity": round(equity, 2),
                "cash": round(strategy.portfolio.cash, 2),
                "positions": len(strategy.portfolio.positions),
                "drawdown": round(dd, 4)
            })

        total_return = (equity - initial_cash) / initial_cash
        trading_days = len(dates)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 0 else 0

        daily_returns_series = pd.Series([
            (equity_curve[j]["equity"] - equity_curve[j-1]["equity"]) / equity_curve[j-1]["equity"]
            if j > 0 and equity_curve[j-1]["equity"] > 0 else 0
            for j in range(len(equity_curve))
        ])
        sharpe = (daily_returns_series.mean() / daily_returns_series.std() * np.sqrt(252)
                  if daily_returns_series.std() > 0 else 0)

        winning = [t for t in trades if t.pnl > 0]
        win_rate = len(winning) / len(trades) if trades else 0
        avg_win = np.mean([t.pnl_pct for t in winning]) if winning else 0
        avg_loss = abs(np.mean([t.pnl_pct for t in trades if t.pnl < 0])) if len([t for t in trades if t.pnl < 0]) > 0 else 0
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        result_id = str(uuid.uuid4())[:8]

        return BacktestResult(
            id=result_id,
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(win_rate, 4),
            profit_loss_ratio=round(pl_ratio, 4),
            trades=trades,
            daily_equity=equity_curve,
            benchmark_compare={}
        )

    def _execute(self, signal: Signal, bars: pd.DataFrame, portfolio: Portfolio,
                 open_trades: dict, trades: list[Trade], dt):
        bar = bars[bars["symbol"] == signal.symbol]
        if bar.empty:
            return
        bar = bar.iloc[0]

        if signal.action == "BUY":
            price = bar["close"] * (1 + self.SLIPPAGE)
            max_shares = int(portfolio.cash * 0.95 / (price * (1 + self.COMMISSION_RATE)))
            shares = min(int(signal.size), max_shares)
            if shares < 100:
                return
            cost = shares * price * (1 + self.COMMISSION_RATE)
            if cost <= portfolio.cash and bar["close"] < bar.get("limit_up", 99999):
                portfolio.add_position(signal.symbol, shares, price, str(dt)[:10])
                open_trades[signal.symbol] = {"date": str(dt)[:10], "price": price, "shares": shares}

        elif signal.action == "SELL":
            if not portfolio.can_sell(signal.symbol):
                return
            price = bar["close"] * (1 - self.SLIPPAGE)
            shares = int(signal.size) if signal.size > 0 else portfolio.positions[signal.symbol]["shares"]
            if shares < 100:
                return
            ot = open_trades.pop(signal.symbol, None)
            entry_price = ot["price"] if ot else portfolio.positions[signal.symbol]["avg_cost"]
            revenue = shares * price * (1 - self.COMMISSION_RATE - self.STAMP_TAX_RATE)
            entry_cost = shares * entry_price * (1 + self.COMMISSION_RATE)
            pnl = revenue - entry_cost
            pnl_pct = pnl / entry_cost if entry_cost else 0
            portfolio.close_position(signal.symbol, price, shares)
            trades.append(Trade(
                symbol=signal.symbol,
                entry_date=ot["date"] if ot else str(dt)[:10],
                exit_date=str(dt)[:10],
                entry_price=round(entry_price, 4),
                exit_price=round(price, 4),
                shares=shares,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 4),
            ))
```

- [ ] **Step 2: Write a sample strategy and run backtest**

Create `backend/strategies/macross.py`:

```python
"""Sample MA crossover strategy."""
import pandas as pd
from backend.engine.strategy import BaseStrategy, Signal
from backend.engine.indicators import sma, cross_over, cross_under


class MACrossover(BaseStrategy):
    def init(self):
        close = self.data.groupby("symbol")["close"]
        self.fast = close.transform(lambda x: sma(x, self.params.get("fast", 5)))
        self.slow = close.transform(lambda x: sma(x, self.params.get("slow", 20)))

    def next(self, i: int) -> Signal | None:
        symbol = self.data["symbol"].iloc[i]
        pf = self.portfolio
        if cross_over(self.fast, self.slow, i):
            return Signal(symbol=symbol, action="BUY", size=pf.cash * 0.3)
        elif cross_under(self.fast, self.slow, i):
            return Signal(symbol=symbol, action="SELL", size=0)
        return None
```

- [ ] **Step 3: Verify backtest**

```bash
cd backend && python -c "
from engine.backtest import BacktestEngine
from strategies.macross import MACrossover
engine = BacktestEngine()
result = engine.run(MACrossover, '2024-01-01', '2024-12-31', ['000001'], 100000)
print(f'Return: {result.total_return:.2%}, Sharpe: {result.sharpe_ratio}, Trades: {len(result.trades)}')
"
```

Expected: backtest result printed with return, Sharpe, and trade count.

- [ ] **Step 4: Commit**

```bash
git add backend/engine/backtest.py backend/strategies/
git commit -m "feat: backtest engine with T+1, fees, circuit breaker"
```

---

### Task 9: 策略 & 回测 API

**Files:**
- Create: `backend/services/strategy_service.py`
- Create: `backend/services/backtest_service.py`
- Create: `backend/api/strategy.py`
- Create: `backend/api/backtest.py`

- [ ] **Step 1: Write `backend/services/strategy_service.py`**

```python
"""Strategy template management."""
import importlib

_TEMPLATES = {
    "ma_crossover": {
        "name": "均线交叉",
        "class": "strategies.macross.MACrossover",
        "params": {"fast": 5, "slow": 20},
        "description": "快线上穿慢线买入，下穿卖出"
    },
}

def list_templates() -> list[dict]:
    return [
        {"id": k, "name": v["name"], "params": v["params"], "description": v["description"]}
        for k, v in _TEMPLATES.items()
    ]

def validate_strategy(strategy_id: str, params: dict) -> dict:
    if strategy_id not in _TEMPLATES:
        return {"valid": False, "error": f"Unknown strategy: {strategy_id}"}
    return {"valid": True, "strategy": _TEMPLATES[strategy_id]["name"]}
```

- [ ] **Step 2: Write `backend/services/backtest_service.py`**

```python
"""Backtest job management."""
import importlib
from typing import Type

from backend.engine.backtest import BacktestEngine, BacktestResult
from backend.engine.strategy import BaseStrategy
from backend.storage.db import get_conn

_engine = BacktestEngine()
_results: dict[str, BacktestResult] = {}

def _load_strategy(class_path: str) -> Type[BaseStrategy]:
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)

def run_backtest(strategy_id: str, start_date: str, end_date: str,
                 universe: list[str], initial_cash: float, params: dict) -> BacktestResult:
    from backend.services.strategy_service import _TEMPLATES
    if strategy_id not in _TEMPLATES:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    template = _TEMPLATES[strategy_id]
    strategy_cls = _load_strategy(template["class"])
    merged_params = {**template["params"], **params}
    result = _engine.run(strategy_cls, start_date, end_date, universe, initial_cash, params=merged_params)
    _results[result.id] = result
    conn = get_conn()
    conn.execute(
        "INSERT INTO backtest_results (id, strategy_name, params, start_date, end_date, universe, metrics) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (result.id, strategy_id, str(merged_params), start_date, end_date,
         ",".join(universe), str({"total_return": result.total_return}))
    )
    conn.commit()
    return result

def get_result(result_id: str) -> BacktestResult:
    if result_id not in _results:
        raise KeyError(f"Result {result_id} not found")
    return _results[result_id]
```

- [ ] **Step 3: Write `backend/api/strategy.py`**

```python
from fastapi import APIRouter
from backend.services.strategy_service import list_templates, validate_strategy

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

@router.get("/templates")
async def templates():
    return list_templates()

@router.post("/validate")
async def validate(req: dict):
    return validate_strategy(req.get("strategy_id", ""), req.get("params", {}))
```

- [ ] **Step 4: Write `backend/api/backtest.py`**

```python
from fastapi import APIRouter
from backend.services.backtest_service import run_backtest, get_result, _results

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

@router.post("/run")
async def run(req: dict):
    result = run_backtest(
        strategy_id=req["strategy_id"],
        start_date=req["start_date"],
        end_date=req["end_date"],
        universe=req["universe"],
        initial_cash=req.get("initial_cash", 100000),
        params=req.get("params", {}),
    )
    return {
        "id": result.id,
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "profit_loss_ratio": result.profit_loss_ratio,
        "trade_count": len(result.trades),
    }

@router.get("/result/{result_id}")
async def result_detail(result_id: str):
    r = get_result(result_id)
    return {
        "id": r.id,
        "total_return": r.total_return,
        "annual_return": r.annual_return,
        "max_drawdown": r.max_drawdown,
        "sharpe_ratio": r.sharpe_ratio,
        "win_rate": r.win_rate,
        "profit_loss_ratio": r.profit_loss_ratio,
        "trades": [t.__dict__ for t in r.trades],
        "daily_equity": r.daily_equity,
    }

@router.get("/results")
async def results_list():
    return list(_results.keys())
```

- [ ] **Step 5: Register new routers in `backend/main.py`**

```python
# Add after existing imports:
from backend.api.strategy import router as strategy_router
from backend.api.backtest import router as backtest_router

# Add after data router registration:
app.include_router(strategy_router)
app.include_router(backtest_router)
```

- [ ] **Step 6: Verify backtest API**

```bash
curl -X POST http://127.0.0.1:8765/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"strategy_id":"ma_crossover","start_date":"2024-01-01","end_date":"2024-12-31","universe":["000001"],"params":{"fast":5,"slow":20}}'
```

Expected: JSON with backtest metrics.

- [ ] **Step 7: Commit**

```bash
git add backend/services/ backend/api/ backend/main.py
git commit -m "feat: strategy and backtest REST API"
```

---

## Phase 3: 参数优化 + 市场情绪

### Task 10: Optuna 参数优化

**Files:**
- Create: `backend/engine/optimizer.py`
- Create: `backend/api/optimize.py`

- [ ] **Step 1: Write `backend/engine/optimizer.py`**

```python
"""Optuna-based strategy parameter optimization."""
import optuna
import pandas as pd
from loguru import logger

from backend.engine.backtest import BacktestEngine
from backend.engine.strategy import BaseStrategy
from backend.storage.cleaner import load_bulk

optuna.logging.set_verbosity(optuna.logging.WARNING)


class StrategyOptimizer:
    def __init__(self, n_trials: int = 100):
        self.n_trials = n_trials
        self.engine = BacktestEngine()

    def optimize(
        self,
        strategy_cls: type[BaseStrategy],
        param_ranges: dict,
        universe: list[str],
        start_date: str,
        end_date: str,
        validation_start: str,
        validation_end: str,
    ) -> dict:
        def objective(trial):
            params = {}
            for name, (low, high, dtype) in param_ranges.items():
                if dtype == "int":
                    params[name] = trial.suggest_int(name, low, high)
                elif dtype == "float":
                    params[name] = trial.suggest_float(name, low, high, log=(low < 0.01))

            try:
                result = self.engine.run(
                    strategy_cls, start_date, end_date,
                    universe, params=params
                )
                val_result = self.engine.run(
                    strategy_cls, validation_start, validation_end,
                    universe, params=params
                )
                return val_result.sharpe_ratio
            except Exception as e:
                logger.warning(f"Trial failed: {e}")
                return -999.0

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)

        best = study.best_params
        best_result = self.engine.run(strategy_cls, start_date, validation_end, universe, params=best)

        stability = self._check_stability(strategy_cls, best, param_ranges, universe,
                                          start_date, validation_end)

        return {
            "best_params": best,
            "best_value": study.best_value,
            "best_result": {
                "total_return": best_result.total_return,
                "sharpe_ratio": best_result.sharpe_ratio,
                "max_drawdown": best_result.max_drawdown,
            },
            "stability": stability,
        }

    def _check_stability(self, strategy_cls, best_params, param_ranges,
                         universe, start, end) -> dict:
        results = {}
        for name in best_params:
            perturbed = []
            for pct in [-0.1, 0, 0.1]:
                val = best_params[name] * (1 + pct)
                if name in param_ranges:
                    low, high, _ = param_ranges[name]
                    val = max(low, min(high, val))
                try:
                    r = self.engine.run(strategy_cls, start, end, universe, params={**best_params, name: val})
                    perturbed.append({"perturbation": f"{pct:+.0%}", "sharpe": r.sharpe_ratio})
                except Exception:
                    pass
            results[name] = perturbed
        return results
```

- [ ] **Step 2: Write `backend/api/optimize.py`**

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/optimize", tags=["optimize"])

@router.post("/run")
async def run_optimize(req: dict):
    import importlib
    from backend.engine.optimizer import StrategyOptimizer
    from backend.services.strategy_service import _TEMPLATES

    strategy_id = req["strategy_id"]
    template = _TEMPLATES[strategy_id]
    mod_path, cls_name = template["class"].rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    strategy_cls = getattr(mod, cls_name)

    opt = StrategyOptimizer(n_trials=req.get("n_trials", 100))
    result = opt.optimize(
        strategy_cls=strategy_cls,
        param_ranges=req["param_ranges"],
        universe=req["universe"],
        start_date=req["start_date"],
        end_date=req["end_date"],
        validation_start=req["validation_start"],
        validation_end=req["validation_end"],
    )
    return result
```

- [ ] **Step 3: Register optimize router in `backend/main.py`**

```python
from backend.api.optimize import router as optimize_router
# ...
app.include_router(optimize_router)
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/optimizer.py backend/api/optimize.py backend/main.py
git commit -m "feat: Optuna parameter optimization engine"
```

---

### Task 11: 市场情绪分析

**Files:**
- Create: `backend/engine/sentiment.py`
- Create: `backend/services/sentiment_service.py`
- Create: `backend/api/sentiment.py`

- [ ] **Step 1: Write `backend/engine/sentiment.py`**

```python
"""Market sentiment scoring engine (0-100 scale)."""
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from loguru import logger

from backend.storage.fetcher import fetch_dragon_tiger, fetch_money_flow
from backend.storage.cleaner import load_cleaned


DEFAULT_WEIGHTS = {
    "money_flow": 0.20,
    "dragon_tiger": 0.20,
    "limit_ratio": 0.20,
    "volume_deviation": 0.20,
    "margin_balance": 0.20,
}

SCORE_RANGE = (0, 100)


def _normalize(series: pd.Series) -> pd.Series:
    """Min-max normalize to 0-100, handling NaN."""
    if series.std() == 0 or series.isna().all():
        return pd.Series(0, index=series.index)
    return ((series - series.min()) / (series.max() - series.min()) * 100).fillna(50)


async def compute_sentiment(date: str = None) -> dict:
    """Compute composite sentiment score for a given date."""
    d = date or datetime.now().strftime("%Y-%m-%d")

    try:
        dragon_df = await fetch_dragon_tiger(d.replace("-", ""))
    except Exception as e:
        logger.warning(f"Dragon tiger fetch failed: {e}")
        dragon_df = pd.DataFrame()

    scores = {}

    # 1. 龙虎榜活跃度: number of stocks appearing
    scores["dragon_tiger"] = min(len(dragon_df) / 20 * 100, 100) if not dragon_df.empty else 50

    # 2. 涨跌停家数比 (simplified: sample of recent data)
    try:
        sample_symbols = ["000001", "000002", "600000", "600036"]
        up_count = 0
        total = 0
        for sym in sample_symbols:
            df = load_cleaned(sym, None, d)
            if len(df) >= 2:
                total += 1
                if df["close"].iloc[-1] > df["close"].iloc[-2]:
                    up_count += 1
        scores["limit_ratio"] = (up_count / total * 100) if total > 0 else 50
    except Exception:
        scores["limit_ratio"] = 50

    # 3. 成交额偏离度: 20-day average deviation
    try:
        df = pd.DataFrame()
        for sym in sample_symbols:
            sym_df = load_cleaned(sym, None, d)
            if len(sym_df) >= 20:
                recent_vol = sym_df["amount"].iloc[-20:]
                avg_vol = recent_vol.mean()
                scores["volume_deviation"] = min((recent_vol.iloc[-1] / avg_vol - 1) * 100 + 50, 100) if avg_vol > 0 else 50
                break
        else:
            scores["volume_deviation"] = 50
    except Exception:
        scores["volume_deviation"] = 50

    # 4. 资金流 (placeholder - would use margin data from AKShare)
    scores["margin_balance"] = 50

    # 5. 资金流方向
    scores["money_flow"] = 50

    composite = sum(scores.get(k, 50) * DEFAULT_WEIGHTS.get(k, 0.2)
                    for k in DEFAULT_WEIGHTS)

    return {
        "date": d,
        "composite": round(composite, 1),
        "components": {k: round(v, 1) for k, v in scores.items()},
        "interpretation": _interpret(composite),
    }


def _interpret(score: float) -> str:
    if score >= 80:
        return "极度乐观"
    elif score >= 60:
        return "偏乐观"
    elif score >= 40:
        return "中性"
    elif score >= 20:
        return "偏悲观"
    return "极度悲观"
```

- [ ] **Step 2: Write `backend/services/sentiment_service.py`**

```python
"""Sentiment data service with caching."""
from datetime import datetime, timedelta
import pandas as pd
from backend.engine.sentiment import compute_sentiment

_cache: dict[str, dict] = {}

async def get_current_sentiment() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in _cache:
        _cache[today] = await compute_sentiment(today)
        _cache.clear()
        _cache[today] = _cache[today]
    return _cache[today]

async def get_sentiment_history(start: str, end: str) -> list[dict]:
    results = []
    current = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while current <= end_ts:
        d = current.strftime("%Y-%m-%d")
        if d in _cache:
            results.append(_cache[d])
        else:
            try:
                r = await compute_sentiment(d)
                _cache[d] = r
                results.append(r)
            except Exception:
                pass
        current += pd.Timedelta(days=1)
    return results
```

- [ ] **Step 3: Write `backend/api/sentiment.py`**

```python
from fastapi import APIRouter
from backend.services.sentiment_service import get_current_sentiment, get_sentiment_history

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

@router.get("/current")
async def current():
    return await get_current_sentiment()

@router.get("/history")
async def history(start: str, end: str):
    return await get_sentiment_history(start, end)
```

- [ ] **Step 4: Register sentiment router in `backend/main.py`**

```python
from backend.api.sentiment import router as sentiment_router
# ...
app.include_router(sentiment_router)
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/sentiment.py backend/services/sentiment_service.py backend/api/sentiment.py backend/main.py
git commit -m "feat: market sentiment analysis with 5-factor scoring"
```

---

## Phase 4: 前端集成

### Task 12: Electron 前端收拢 & 基础布局

**Files:**
- Move: `index.html`, `main.js`, `renderer.js`, `package.json` → `frontend/`
- Create: `frontend/app.py` (Python 启动脚本，自动拉起后端和 Electron)

- [ ] **Step 1: Move frontend files**

```bash
mkdir -p frontend
mv index.html main.js renderer.js package.json package-lock.json node_modules frontend/
```

- [ ] **Step 2: Create `frontend/launch.py`** (统一启动脚本)

```python
"""Launch backend + Electron frontend together."""
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent / "backend"

def main():
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "8765"],
        cwd=str(BACKEND_DIR)
    )
    time.sleep(2)
    print("Backend started at http://127.0.0.1:8765")
    webbrowser.open("http://127.0.0.1:8765/docs")
    try:
        backend.wait()
    except KeyboardInterrupt:
        backend.terminate()

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update `frontend/renderer.js` to call backend APIs**

Replace placeholder code with:

```javascript
const API = 'http://127.0.0.1:8765';

async function loadStocks() {
  const res = await fetch(`${API}/api/data/stocks`);
  return res.json();
}

async function runBacktest(config) {
  const res = await fetch(`${API}/api/backtest/run`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(config),
  });
  return res.json();
}

async function loadSentiment() {
  const res = await fetch(`${API}/api/sentiment/current`);
  return res.json();
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: reorganize frontend and wire backend API calls"
```

---

## Completion Summary

- **Total tasks**: 12
- **Total steps**: ~50
- **Estimated effort**: 4-6 hours for a single developer
- **Prerequisites**: Python 3.11+, Node.js (for Electron), pip
```

参考实现计划输出的代码要求和风格

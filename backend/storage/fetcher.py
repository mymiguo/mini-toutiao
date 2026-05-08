"""Data fetcher for AKShare (primary) with BaoStock fallback."""
import asyncio
from datetime import datetime
from typing import Optional

import akshare as ak
import pandas as pd
from loguru import logger

from backend.config import settings as cfg

MAX_RETRIES = 3
BASE_DELAY = 1.0

_rate_sem = asyncio.Semaphore(cfg.get("data", {}).get("rate_limit", 10))


async def _rate_limited_call(fn, *args, **kwargs):
    async with _rate_sem:
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
        raise RuntimeError(f"All {MAX_RETRIES} attempts exhausted for {fn.__name__}") from e


async def fetch_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = await _rate_limited_call(_akshare_daily, symbol, start_date, end_date)
    except Exception:
        logger.info(f"AKShare failed for {symbol}, falling back to BaoStock")
        df = await _rate_limited_call(_baostock_daily, symbol, start_date, end_date)
    if df.empty:
        return df
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
        "成交额": "amount",
    })
    keep_cols = ["date", "open", "high", "low", "close", "volume", "amount"]
    df = df[[c for c in keep_cols if c in df.columns]].copy()
    for c in ["open", "high", "low", "close"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["symbol"] = symbol
    return df


def _akshare_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    return ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        adjust="qfq"
    )


def _baostock_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise ConnectionError(f"BaoStock login failed: {lg.error_msg}")
    try:
        code = ("sh." if symbol.startswith("6") else "sz.") + symbol
        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,amount",
            start_date=start, end_date=end, frequency="d",
            adjustflag="2"
        )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return pd.DataFrame(rows, columns=["date","open","high","low","close","volume","amount"])
    finally:
        bs.logout()


async def fetch_stock_list() -> pd.DataFrame:
    return await _rate_limited_call(ak.stock_info_a_code_name)


async def fetch_financials(symbol: str) -> dict:
    try:
        df = await _rate_limited_call(ak.stock_financial_abstract_ths, symbol)
        return {"symbol": symbol, "data": df}
    except Exception as e:
        logger.error(f"Failed to fetch financials for {symbol}: {e}")
        return {"symbol": symbol, "data": pd.DataFrame(), "error": str(e)}


async def fetch_dragon_tiger(date: Optional[str] = None) -> pd.DataFrame:
    d = date or datetime.now().strftime("%Y%m%d")
    return await _rate_limited_call(ak.stock_lhb_detail_em, date=d)


async def fetch_money_flow(symbol: str) -> pd.DataFrame:
    market = "sh" if symbol.startswith("6") else "sz"
    return await _rate_limited_call(ak.stock_individual_fund_flow, stock=symbol, market=market)

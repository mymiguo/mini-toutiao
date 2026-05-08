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

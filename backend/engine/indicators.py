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
    vol_dist = {}
    for i in range(bins):
        mask = (close >= price_range[i]) & (close < price_range[i+1])
        if i == bins - 1:
            mask = (close >= price_range[i]) & (close <= price_range[i+1])
        vol_dist[labels[i]] = volume[mask].sum()
    return vol_dist

def cross_over(a: pd.Series, b: pd.Series, i: int) -> bool:
    if i < 1:
        return False
    return a.iloc[i] > b.iloc[i] and a.iloc[i-1] <= b.iloc[i-1]

def cross_under(a: pd.Series, b: pd.Series, i: int) -> bool:
    if i < 1:
        return False
    return a.iloc[i] < b.iloc[i] and a.iloc[i-1] >= b.iloc[i-1]

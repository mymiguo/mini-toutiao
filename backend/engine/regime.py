"""Market regime detection engine.

Classifies market state into regimes to adapt strategy behavior:
  - TRENDING_UP: strong bullish trend, trend-following works best
  - TRENDING_DOWN: strong bearish, avoid long positions
  - CHOPPY: sideways/volatile, trend strategies fail
  - QUIET: low volatility consolidation, wait for breakout
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Regime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    CHOPPY = "choppy"
    QUIET = "quiet"


@dataclass
class RegimeResult:
    regime: Regime
    confidence: float
    trend_strength: float  # ADX-like
    volatility: float       # normalized ATR/close
    efficiency: float       # price efficiency (net change / total path)


def detect_regime(df: pd.DataFrame, window: int = 20) -> RegimeResult:
    """Detect current market regime from recent price data.

    Uses three dimensions:
      1. Trend strength (ADX-like directional movement)
      2. Volatility regime (ATR/close normalized)
      3. Price efficiency (net change / sum of absolute daily changes)

    Args:
        df: DataFrame with at least 'close', 'high', 'low' columns
        window: lookback period (default 20 days)
    """
    if len(df) < window:
        return RegimeResult(Regime.QUIET, 0.5, 0.0, 0.0, 0.0)

    recent = df.tail(window).copy()
    close = recent["close"].values
    high = recent["high"].values
    low = recent["low"].values

    # 1. Trend strength: ADX-like using +/-DM
    up_move = np.diff(high)
    down_move = -np.diff(low)
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - close[:-1]),
        np.abs(low[1:] - close[:-1])
    ])

    atr_val = np.mean(tr[-min(window-1, len(tr)):]) if len(tr) > 0 else 0
    smooth_tr = pd.Series(tr).ewm(alpha=1/window, adjust=False).mean().iloc[-1] if len(tr) > 0 else 1

    smooth_plus = pd.Series(plus_dm).ewm(alpha=1/window, adjust=False).mean().iloc[-1] if len(plus_dm) > 0 else 0
    smooth_minus = pd.Series(minus_dm).ewm(alpha=1/window, adjust=False).mean().iloc[-1] if len(minus_dm) > 0 else 0

    if smooth_tr > 0:
        plus_di = 100 * smooth_plus / smooth_tr
        minus_di = 100 * smooth_minus / smooth_tr
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0
    else:
        plus_di = minus_di = dx = 0

    trend_strength = round(dx, 2)
    trend_direction = plus_di - minus_di

    # 2. Volatility regime: ATR / close
    avg_close = np.mean(close)
    volatility = round(atr_val / avg_close, 4) if avg_close > 0 else 0

    # 3. Price efficiency: |net change| / sum of |daily changes|
    net_change = abs(close[-1] - close[0])
    total_path = np.sum(np.abs(np.diff(close)))
    efficiency = round(net_change / total_path, 4) if total_path > 0 else 0

    # Regime classification
    if volatility < 0.01:
        regime = Regime.QUIET
        confidence = 0.7
    elif trend_strength > 25 and efficiency > 0.3:
        if trend_direction > 0:
            regime = Regime.TRENDING_UP
            confidence = min(0.9, 0.5 + trend_strength / 100)
        else:
            regime = Regime.TRENDING_DOWN
            confidence = min(0.9, 0.5 + trend_strength / 100)
    elif efficiency < 0.15 or (trend_strength < 20 and volatility > 0.02):
        regime = Regime.CHOPPY
        confidence = 0.6
    else:
        regime = Regime.QUIET
        confidence = 0.5

    return RegimeResult(
        regime=regime,
        confidence=round(confidence, 2),
        trend_strength=trend_strength,
        volatility=volatility,
        efficiency=efficiency,
    )

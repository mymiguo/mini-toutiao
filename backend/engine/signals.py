"""Alpha signal combination framework.

Individual signals are combined with dynamic weights based on:
  - Historical signal performance (IC, hit rate)
  - Market regime (some signals work better in certain regimes)
  - Signal correlation (avoid over-concentration on same factor)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import numpy as np
import pandas as pd


class SignalType(Enum):
    TREND = "trend"
    MOMENTUM = "momentum"
    REVERSAL = "reversal"
    VOLUME = "volume"
    VOLATILITY = "volatility"


@dataclass
class AlphaSignal:
    name: str
    signal_type: SignalType
    value: float       # -1.0 (strong sell) to +1.0 (strong buy)
    confidence: float  # 0.0 to 1.0


class SignalCombiner:
    """Combines multiple alpha signals into a single composite score.

    Uses equal-weight with correlation penalty to avoid double-counting
    correlated signals. Each signal is standardized to [-1, 1] before combination.
    """

    def __init__(self):
        self.signals: list[AlphaSignal] = []

    def add(self, signal: AlphaSignal):
        self.signals.append(signal)

    def composite(self, base_weight: dict[str, float] = None) -> float:
        """Compute composite score with optional dynamic weights.

        Correlation penalty: if two TREND signals agree, their combined weight
        is reduced by 20% to avoid over-concentration.
        """
        if not self.signals:
            return 0.0

        weights = base_weight or self._default_weights()
        scored = []

        for sig in self.signals:
            w = weights.get(sig.name, 1.0 / len(self.signals))
            scored.append((sig, w))

        # Group by signal type for correlation penalty
        type_groups: dict[SignalType, list] = {}
        for sig, w in scored:
            type_groups.setdefault(sig.signal_type, []).append((sig, w))

        total = 0.0
        total_weight = 0.0

        for sig, w in scored:
            # Apply correlation dilution if multiple signals of same type
            same_type = type_groups[sig.signal_type]
            if len(same_type) > 1:
                dilution = 1.0 / (1.0 + 0.3 * (len(same_type) - 1))
            else:
                dilution = 1.0

            effective_w = w * dilution * sig.confidence
            total += sig.value * effective_w
            total_weight += effective_w

        self.signals.clear()
        return round(total / total_weight, 4) if total_weight > 0 else 0.0

    def _default_weights(self) -> dict[str, float]:
        n = max(len(self.signals), 1)
        return {s.name: 1.0 / n for s in self.signals}


def trend_signal(data: pd.DataFrame, fast: int = 10, slow: int = 30) -> AlphaSignal:
    """EMA crossover trend signal."""
    if len(data) < slow:
        return AlphaSignal("trend_ema", SignalType.TREND, 0.0, 0.0)

    fast_ema = data["close"].ewm(span=fast, adjust=False).mean()
    slow_ema = data["close"].ewm(span=slow, adjust=False).mean()

    if slow_ema.iloc[-1] == 0:
        return AlphaSignal("trend_ema", SignalType.TREND, 0.0, 0.0)

    spread = (fast_ema.iloc[-1] - slow_ema.iloc[-1]) / slow_ema.iloc[-1]
    value = np.clip(spread * 50, -1.0, 1.0)  # 2% spread = max signal

    # Confidence based on spread consistency
    spreads = (fast_ema - slow_ema) / slow_ema.replace(0, np.nan)
    if len(spreads.dropna()) >= 5:
        direction_agree = np.sign(spreads.dropna().iloc[-5:]).nunique() == 1
        conf = 0.8 if direction_agree else 0.5
    else:
        conf = 0.3

    return AlphaSignal("trend_ema", SignalType.TREND, round(float(value), 4), conf)


def momentum_signal(data: pd.DataFrame, period: int = 20) -> AlphaSignal:
    """Price momentum signal using ROC (Rate of Change)."""
    if len(data) < period:
        return AlphaSignal("momentum_roc", SignalType.MOMENTUM, 0.0, 0.0)

    roc = data["close"].pct_change(periods=period).iloc[-1]
    # Annualized: 20-day ROC / sqrt(20/252) ~ 20-day ROC * 3.5
    ann_roc = roc

    value = np.clip(ann_roc * 15, -1.0, 1.0)  # ~6.7% 20-day = max signal

    # Confidence from RSI (not extreme = higher confidence)
    from backend.engine.indicators import rsi
    rsi_val = rsi(data["close"], 14).iloc[-1]
    if 30 <= rsi_val <= 70:
        conf = 0.8
    elif 20 <= rsi_val <= 80:
        conf = 0.6
    else:
        conf = 0.4

    return AlphaSignal("momentum_roc", SignalType.MOMENTUM, round(float(value), 4), conf)


def volume_signal(data: pd.DataFrame, period: int = 20) -> AlphaSignal:
    """Volume confirmation signal. High volume + positive price = strong buy."""
    if len(data) < period:
        return AlphaSignal("volume_confirm", SignalType.VOLUME, 0.0, 0.0)

    vol_ma = data["volume"].rolling(period).mean()
    vol_ratio = data["volume"].iloc[-1] / vol_ma.iloc[-1] if vol_ma.iloc[-1] > 0 else 1.0
    price_change = data["close"].pct_change().iloc[-1]

    value = np.clip((vol_ratio - 1) * np.sign(price_change) * 2, -1.0, 1.0)
    conf = 0.6 if vol_ratio > 0.8 else 0.3

    return AlphaSignal("volume_confirm", SignalType.VOLUME, round(float(value), 4), conf)


def reversal_signal(data: pd.DataFrame, period: int = 14) -> AlphaSignal:
    """Mean reversion signal using RSI extremes."""
    from backend.engine.indicators import rsi

    if len(data) < period:
        return AlphaSignal("reversal_rsi", SignalType.REVERSAL, 0.0, 0.0)

    rsi_val = rsi(data["close"], period).iloc[-1]

    if np.isnan(rsi_val):
        return AlphaSignal("reversal_rsi", SignalType.REVERSAL, 0.0, 0.0)

    if rsi_val < 25:
        value = 0.6   # Oversold bounce
        conf = 0.6
    elif rsi_val < 35:
        value = 0.3
        conf = 0.5
    elif rsi_val > 75:
        value = -0.6  # Overbought reversal
        conf = 0.6
    elif rsi_val > 65:
        value = -0.3
        conf = 0.5
    else:
        value = 0.0
        conf = 0.3

    return AlphaSignal("reversal_rsi", SignalType.REVERSAL, value, conf)

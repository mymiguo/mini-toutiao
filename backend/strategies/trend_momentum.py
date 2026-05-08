"""Robust multi-factor trend-following strategy.

Factors:
  1. Trend: EMA fast/slow crossover with trend filter (EMA medium)
  2. Momentum: RSI confirmation (avoid overbought/oversold traps)
  3. Volume: volume > 20-day average confirms signal
  4. Volatility: ATR-based dynamic stop-loss and position sizing
"""
import pandas as pd
import numpy as np
from backend.engine.strategy import BaseStrategy, Signal
from backend.engine.indicators import ema, rsi, atr, cross_over, cross_under


class TrendMomentum(BaseStrategy):

    def init(self):
        df = self.data
        p = self.params

        # Trend indicators
        self.fast_ema = df.groupby("symbol")["close"].transform(lambda x: ema(x, p.get("fast", 10)))
        self.slow_ema = df.groupby("symbol")["close"].transform(lambda x: ema(x, p.get("slow", 30)))
        self.trend_ema = df.groupby("symbol")["close"].transform(lambda x: ema(x, p.get("trend", 60)))

        # Momentum filter
        self.rsi = df.groupby("symbol")["close"].transform(lambda x: rsi(x, p.get("rsi_period", 14)))

        # Volume confirmation
        self.vol_ma = df.groupby("symbol")["volume"].transform(lambda x: x.rolling(p.get("vol_period", 20)).mean())

        # ATR for stop-loss and position sizing (compute per symbol)
        atr_parts = []
        for sym in df["symbol"].unique():
            sdf = df[df["symbol"] == sym]
            s_atr = atr(sdf["high"], sdf["low"], sdf["close"], p.get("atr_period", 14))
            atr_parts.append(s_atr)
        self.atr = pd.concat(atr_parts).reindex(df.index)

        # Per-symbol state
        self.stop_loss: dict[str, float] = {}
        self.entry_prices: dict[str, float] = {}

    def next(self, i: int) -> Signal | None:
        symbol = self.data["symbol"].iloc[i]
        row = self.data.iloc[i]
        pf = self.portfolio

        # --- Exit check: ATR trailing stop ---
        if symbol in pf.positions and pf.can_sell(symbol):
            stop = self.stop_loss.get(symbol)
            if stop and row["close"] < stop:
                return Signal(symbol=symbol, action="SELL", size=0)

        # --- Entry conditions ---
        # Filter 1: price above long-term trend (only go long in uptrend)
        price = row["close"]
        trend_val = self.trend_ema.iloc[i]
        if pd.isna(trend_val) or price < trend_val:
            return None

        # Filter 2: volume confirmation
        vol_val = row["volume"]
        vol_ma_val = self.vol_ma.iloc[i]
        if pd.isna(vol_ma_val) or vol_val < vol_ma_val:
            return None

        # Filter 3: RSI filter (not overbought, not extreme oversold dead-cat)
        rsi_val = self.rsi.iloc[i]
        rsi_low = self.params.get("rsi_low", 35)
        rsi_high = self.params.get("rsi_high", 65)
        if pd.isna(rsi_val) or rsi_val < rsi_low or rsi_val > rsi_high:
            return None

        # Signal: EMA golden cross
        if cross_over(self.fast_ema, self.slow_ema, i):
            atr_val = self.atr.iloc[i]
            if pd.isna(atr_val) or atr_val <= 0:
                return None

            # ATR-based position sizing: risk 2% of portfolio per trade
            risk_pct = self.params.get("risk_pct", 0.02)
            risk_amount = pf.cash * risk_pct
            stop_distance = atr_val * self.params.get("stop_atr_mult", 2.0)
            position_size = risk_amount / stop_distance if stop_distance > 0 else pf.cash * 0.1

            self.stop_loss[symbol] = price - stop_distance
            self.entry_prices[symbol] = price

            return Signal(symbol=symbol, action="BUY", size=position_size)

        # Signal: EMA death cross
        if cross_under(self.fast_ema, self.slow_ema, i):
            if pf.can_sell(symbol):
                return Signal(symbol=symbol, action="SELL", size=0)

        return None

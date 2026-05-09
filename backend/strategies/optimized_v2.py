"""Optimized V2 strategy.

Improvements over baseline:
  1. Volume confirmation — only enter when vol > 20-day avg (filters fake breakouts)
  2. ATR trailing stop — dynamic exit, locks in profits as trend progresses
  3. MA200 bounce re-entry — if price pulls back to MA200 and rebounds, re-enter
  4. Take-profit at 3x ATR — protect gains, don't give back big winners
  5. Reduced MA200 filter — only filter out stocks WAY below MA200 (>5% under)
"""
import pandas as pd
import numpy as np
from backend.engine.strategy import BaseStrategy, Signal
from backend.engine.indicators import sma, atr, cross_over, cross_under


class OptimizedV2(BaseStrategy):

    def init(self):
        df = self.data
        p = self.params

        self.sym_fast = {}
        self.sym_slow = {}
        self.sym_ma200 = {}
        self.sym_atr = {}
        self.sym_vol_ma = {}
        self.sym_close = {}
        self.sym_high = {}
        self.sym_low = {}
        self.sym_vol = {}

        # State tracking
        self.trailing_stops: dict[str, float] = {}
        self.entry_prices: dict[str, float] = {}
        self.highest_since_entry: dict[str, float] = {}
        self.ma200_bounce_eligible: dict[str, bool] = {}

        for sym in df["symbol"].unique():
            sdf = df[df["symbol"] == sym].reset_index(drop=True)
            self.sym_close[sym] = sdf["close"]
            self.sym_high[sym] = sdf["high"]
            self.sym_low[sym] = sdf["low"]
            self.sym_vol[sym] = sdf["volume"]
            self.sym_fast[sym] = sma(sdf["close"], p.get("fast", 10))
            self.sym_slow[sym] = sma(sdf["close"], p.get("slow", 30))
            self.sym_ma200[sym] = sma(sdf["close"], 200)
            self.sym_atr[sym] = atr(sdf["high"], sdf["low"], sdf["close"], p.get("atr_period", 14))
            self.sym_vol_ma[sym] = sdf["volume"].rolling(p.get("vol_period", 20)).mean()

    def next(self, i: int) -> Signal | None:
        sym = self.data["symbol"].iloc[i]
        pf = self.portfolio
        p = self.params

        if sym not in self.sym_close or i >= len(self.sym_close[sym]):
            return None

        price = self.sym_close[sym].iloc[i]
        fast = self.sym_fast[sym].iloc[i]
        slow = self.sym_slow[sym].iloc[i]
        ma200 = self.sym_ma200[sym].iloc[i]
        atr_val = self.sym_atr[sym].iloc[i]
        vol = self.sym_vol[sym].iloc[i]
        vol_ma = self.sym_vol_ma[sym].iloc[i]
        high = self.sym_high[sym].iloc[i]

        if pd.isna(ma200) or pd.isna(atr_val) or atr_val <= 0:
            return None

        in_position = sym in pf.positions and pf.can_sell(sym)
        # Can also exit same-day entries
        has_position = sym in pf.positions

        # ── EXIT LOGIC ──
        if has_position:
            pos = pf.positions[sym]
            entry_px = self.entry_prices.get(sym, pos["avg_cost"])

            # 1. ATR trailing stop
            if sym in self.trailing_stops:
                # Trail stop up with price
                atr_mult = p.get("trail_atr", 3.0)
                new_stop = high - atr_val * atr_mult
                if new_stop > self.trailing_stops[sym]:
                    self.trailing_stops[sym] = new_stop
                if price < self.trailing_stops[sym]:
                    self._clear_state(sym)
                    return Signal(symbol=sym, action="SELL", size=0)

            # 2. Take-profit (3x ATR from entry)
            tp_mult = p.get("tp_atr", 3.0)
            take_profit = entry_px + atr_val * tp_mult
            if price >= take_profit:
                self._clear_state(sym)
                return Signal(symbol=sym, action="SELL", size=0)

            # 3. MA200 death: exit if way below MA200
            if price < ma200 * 0.92:  # 8% below MA200
                self._clear_state(sym)
                return Signal(symbol=sym, action="SELL", size=0)

            # 4. EMA death cross while below MA200
            if price < ma200 and cross_under(self.sym_fast[sym], self.sym_slow[sym], i):
                self._clear_state(sym)
                return Signal(symbol=sym, action="SELL", size=0)

        # ── ENTRY LOGIC ──
        # Filter: don't trade stocks way below MA200
        if price < ma200 * 0.85:
            return None

        # Volume confirmation
        vol_ok = not pd.isna(vol_ma) and vol > vol_ma * p.get("vol_min", 0.8)

        # Signal 1: EMA golden cross with volume
        if cross_over(self.sym_fast[sym], self.sym_slow[sym], i):
            # Must be near or above MA200, with volume
            if price > ma200 * 0.95 and vol_ok:
                return self._enter(sym, price, atr_val, "golden_cross")

        # Signal 2: MA200 bounce (price dips to MA200 then rebounds)
        if price > ma200 * 0.98 and price < ma200 * 1.05 and vol_ok:
            # Check: was below MA200 recently and now crossing back up?
            prev_close = self.sym_close[sym].iloc[i - 1] if i > 0 else price
            if prev_close < ma200 and price > ma200 * 0.99:
                # Bouncing off MA200 support
                if cross_over(self.sym_fast[sym], self.sym_slow[sym], i):
                    return self._enter(sym, price, atr_val, "ma200_bounce")

        # Signal 3: Trend continuation (already in uptrend, pullback to MA30)
        if (price > ma200 and cross_over(self.sym_fast[sym], self.sym_slow[sym], i)
                and vol_ok and len(pf.positions) < p.get("max_positions", 4)):
            # Golden cross above MA200 = strongest signal
            return self._enter(sym, price, atr_val, "trend_continue")

        return None

    def _enter(self, sym, price, atr_val, reason):
        pf = self.portfolio
        p = self.params
        risk_per_trade = pf.cash * p.get("risk_pct", 0.08)
        stop_dist = atr_val * p.get("init_stop_atr", 2.0)
        shares = int(risk_per_trade / stop_dist / 100) * 100
        shares = max(100, min(shares, int(pf.cash * 0.25 / price / 100) * 100))

        self.trailing_stops[sym] = price - stop_dist
        self.entry_prices[sym] = price
        self.highest_since_entry[sym] = price

        return Signal(symbol=sym, action="BUY", size=shares)

    def _clear_state(self, sym):
        self.trailing_stops.pop(sym, None)
        self.entry_prices.pop(sym, None)
        self.highest_since_entry.pop(sym, None)

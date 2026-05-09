"""Adaptive multi-signal quantitative strategy.

Combines regime detection, alpha signal fusion, and dynamic risk management.
  - Trending: weights trend + momentum signals
  - Choppy: reduces exposure, favors mean-reversion
  - Bear: largely stays in cash or very small positions
"""

import pandas as pd
import numpy as np
from backend.engine.strategy import BaseStrategy, Signal
from backend.engine.indicators import atr
from backend.engine.regime import detect_regime, Regime
from backend.engine.signals import (
    SignalCombiner, AlphaSignal, SignalType,
    trend_signal, momentum_signal, volume_signal, reversal_signal,
)
from backend.engine.risk_manager import RiskManager, PositionSize


class AdaptiveQuant(BaseStrategy):
    """Regime-adaptive multi-factor strategy."""

    def init(self):
        df = self.data
        p = self.params

        self.risk_mgr = RiskManager(
            max_position_pct=p.get("max_pos_pct", 0.15),
            vol_target=p.get("vol_target", 0.15),
            kelly_fraction=p.get("kelly_frac", 0.25),
        )

        # Per-symbol data and state
        self.sym_data: dict[str, pd.DataFrame] = {}
        self.sym_atr: dict[str, pd.Series] = {}
        self.sym_regime: dict[str, Regime] = {}
        self.sym_stops: dict[str, float] = {}
        self.sym_winrates: dict[str, list] = {}
        self.sym_trade_pnl: dict[str, list] = {}

        symbols = sorted(df["symbol"].unique())
        atr_period = p.get("atr_period", 14)

        for sym in symbols:
            sdf = df[df["symbol"] == sym].reset_index(drop=True)
            self.sym_data[sym] = sdf
            self.sym_atr[sym] = atr(sdf["high"], sdf["low"], sdf["close"], atr_period)
            self.sym_winrates[sym] = []
            self.sym_trade_pnl[sym] = []

    def next(self, i: int) -> Signal | None:
        symbol = self.data["symbol"].iloc[i]
        sdf = self.sym_data.get(symbol)
        if sdf is None:
            return None

        # Find this symbol's row index
        sym_row = sdf[sdf["date"] == self.data["date"].iloc[i]]
        if sym_row.empty:
            return None
        sym_i = sdf.index.get_loc(sym_row.index[0])

        pf = self.portfolio
        price = sdf["close"].iloc[sym_i]
        if pd.isna(price) or price <= 0:
            return None

        # Exit signal: stop loss check
        if symbol in pf.positions and pf.can_sell(symbol):
            stop = self.sym_stops.get(symbol)
            if stop and price < stop:
                # Record trade outcome
                pos = pf.positions[symbol]
                pnl = (price - pos["avg_cost"]) / pos["avg_cost"]
                self.sym_trade_pnl[symbol].append(pnl)
                self.sym_stops.pop(symbol, None)
                return Signal(symbol=symbol, action="SELL", size=0)

        # --- Entry logic ---
        # 1. Detect current regime
        hist = sdf.iloc[:sym_i + 1].tail(60)
        regime_result = detect_regime(hist)
        self.sym_regime[symbol] = regime_result.regime

        # Don't enter in bear / choppy (only exit)
        p = self.params
        if regime_result.regime in (Regime.TRENDING_DOWN, Regime.CHOPPY):
            if p.get("bear_mode", "defensive") == "defensive":
                return None

        # 2. Compute alpha signals
        combiner = SignalCombiner()
        combiner.add(trend_signal(hist, p.get("fast", 10), p.get("slow", 30)))
        combiner.add(momentum_signal(hist, p.get("mom_period", 20)))

        if p.get("use_volume", True):
            combiner.add(volume_signal(hist))
        if regime_result.regime == Regime.CHOPPY:
            combiner.add(reversal_signal(hist))

        # 3. Regime-aware signal weighting
        if regime_result.regime == Regime.TRENDING_UP:
            weights = {"trend_ema": 0.4, "momentum_roc": 0.35, "volume_confirm": 0.15, "reversal_rsi": 0.10}
        elif regime_result.regime == Regime.CHOPPY:
            weights = {"trend_ema": 0.2, "momentum_roc": 0.2, "volume_confirm": 0.2, "reversal_rsi": 0.4}
        else:
            weights = {"trend_ema": 0.35, "momentum_roc": 0.35, "volume_confirm": 0.2, "reversal_rsi": 0.1}

        composite = combiner.composite(weights)

        if composite < 0.2 and symbol in pf.positions and pf.can_sell(symbol):
            return Signal(symbol=symbol, action="SELL", size=0)

        if composite < 0.3:
            return None

        # 4. Position sizing via RiskManager
        atr_val = self.sym_atr[symbol].iloc[sym_i] if sym_i < len(self.sym_atr[symbol]) else None

        wr = 0.5
        if len([p for p in self.sym_trade_pnl[symbol] if p > 0]) >= 3:
            wins = [p for p in self.sym_trade_pnl[symbol] if p > 0]
            losses = [p for p in self.sym_trade_pnl[symbol] if p < 0]
            wr = len(wins) / len(self.sym_trade_pnl[symbol])
            wl_ratio = np.mean(wins) / abs(np.mean(losses)) if losses and np.mean(losses) != 0 else 2.0
        else:
            wl_ratio = 2.0

        pos = self.risk_mgr.size_position(
            pf.cash, price, composite,
            atr=atr_val, win_rate=wr, avg_win_loss_ratio=wl_ratio,
        )

        if pos.shares < 100:
            return None

        self.sym_stops[symbol] = pos.stop_price
        return Signal(symbol=symbol, action="BUY", size=pos.shares)

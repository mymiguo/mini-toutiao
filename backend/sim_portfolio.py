"""Simulated investment portfolio — tracks performance from inception date.

Uses the same MA10/30 + MA200 strategy to select positions at start date,
then tracks buy-and-hold performance vs strategy rebalancing.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from backend.engine.indicators import sma, atr
from backend.storage.cleaner import load_cleaned


class SimPortfolio:
    def __init__(self, capital=100000, start_date="2026-04-08"):
        self.capital = capital
        self.cash = capital
        self.start_date = start_date
        self.positions = {}  # sym -> {shares, entry_price, cost}
        self.trades = []
        self.daily_nav = []

    def select_positions(self, candidates, top_n=5):
        """Select top N stocks from candidates based on strategy score at start date."""
        scored = []
        for sym, name, sector in candidates:
            try:
                df = load_cleaned(sym)
                if df.empty or len(df) < 200:
                    continue
                df = df.sort_values("date")
                # Get data up to start date
                mask = df["date"] <= self.start_date
                hist = df[mask]
                if len(hist) < 200:
                    continue

                c = hist["close"]
                p = c.iloc[-1]
                ma200 = sma(c, 200).iloc[-1]
                ma10 = sma(c, 10).iloc[-1]
                ma30 = sma(c, 30).iloc[-1]

                if np.isnan(ma200) or p <= ma200 or ma10 <= ma30:
                    continue

                # Score: strength + regime
                strength = (p - ma200) / ma200
                scored.append((sym, name, sector, p, ma200, strength))
            except Exception:
                pass

        # Pick top N by strength, one per sector
        scored.sort(key=lambda x: x[5], reverse=True)
        selected = []
        used_sectors = set()
        for s in scored:
            if s[2] not in used_sectors and len(selected) < top_n:
                selected.append(s)
                used_sectors.add(s[2])

        return selected

    def execute_buys(self, selected):
        """Buy selected stocks at start date prices."""
        per_stock = self.capital / len(selected) if selected else 0
        for sym, name, sector, price, ma200, strength in selected:
            shares = int(per_stock / price / 100) * 100
            if shares < 100:
                shares = 100
            cost = shares * price
            if cost <= self.cash:
                self.cash -= cost
                self.positions[sym] = {
                    "name": name,
                    "sector": sector,
                    "shares": shares,
                    "entry_price": price,
                    "cost": cost,
                    "entry_ma200": ma200,
                    "entry_strength": strength,
                }
                self.trades.append({
                    "date": self.start_date,
                    "action": "BUY",
                    "symbol": sym,
                    "name": name,
                    "price": price,
                    "shares": shares,
                    "cost": cost,
                })

    def track(self):
        """Track daily NAV from start to latest."""
        # Collect all dates
        all_dates = set()
        price_cache = {}
        for sym in self.positions:
            df = load_cleaned(sym)
            if df.empty:
                continue
            df = df.sort_values("date")
            mask = (df["date"] >= self.start_date) & (df["date"] <= datetime.now().strftime("%Y-%m-%d"))
            df = df[mask]
            for _, row in df.iterrows():
                all_dates.add(str(row["date"])[:10])
                price_cache[(sym, str(row["date"])[:10])] = float(row["close"])

        all_dates = sorted(all_dates)
        peak = self.capital + sum(p["cost"] for p in self.positions.values())

        for d in all_dates:
            equity = self.cash
            pos_value = 0
            for sym, pos in self.positions.items():
                px = price_cache.get((sym, d))
                if px is None:
                    # Use last known price
                    for dd in reversed(all_dates):
                        px = price_cache.get((sym, dd))
                        if px is not None:
                            break
                if px:
                    pos_value += pos["shares"] * px

            equity += pos_value
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            self.daily_nav.append({
                "date": d,
                "equity": round(equity, 2),
                "drawdown": round(dd, 4),
            })

    def summary(self):
        """Generate portfolio performance summary."""
        if not self.daily_nav:
            return {}
        start_val = self.daily_nav[0]["equity"]
        current_val = self.daily_nav[-1]["equity"]
        total_ret = (current_val - start_val) / start_val
        peak = max(d["equity"] for d in self.daily_nav)
        max_dd = max(d["drawdown"] for d in self.daily_nav)

        positions_detail = []
        total_current = self.cash
        for sym, pos in self.positions.items():
            current_px = None
            for d in reversed(self.daily_nav):
                # Get latest price
                df = load_cleaned(sym)
                if not df.empty:
                    df = df.sort_values("date")
                    latest = df[df["date"] <= datetime.now().strftime("%Y-%m-%d")]
                    if not latest.empty:
                        current_px = float(latest["close"].iloc[-1])
                        break
            if current_px is None:
                current_px = pos["entry_price"]
            val = pos["shares"] * current_px
            pnl = val - pos["cost"]
            pnl_pct = pnl / pos["cost"]
            total_current += val
            positions_detail.append({
                "symbol": sym,
                "name": pos["name"],
                "sector": pos["sector"],
                "shares": pos["shares"],
                "entry_price": pos["entry_price"],
                "current_price": round(current_px, 2),
                "cost": round(pos["cost"], 2),
                "value": round(val, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 4),
                "entry_strength": pos["entry_strength"],
            })

        return {
            "start_date": self.start_date,
            "end_date": self.daily_nav[-1]["date"],
            "start_value": round(start_val, 2),
            "current_value": round(total_current, 2),
            "total_return": round(total_ret, 4),
            "max_drawdown": round(max_dd, 4),
            "positions": positions_detail,
            "daily_nav": self.daily_nav,
            "trades": self.trades,
        }

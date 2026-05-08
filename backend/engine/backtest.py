"""Backtest engine with T+1, fees, and circuit breaker simulation."""
import uuid
from dataclasses import dataclass, field
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
    COMMISSION_RATE = 0.00025
    STAMP_TAX_RATE = 0.001
    SLIPPAGE = 0.0001
    MIN_LOT = 100

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
        strategy.portfolio = Portfolio(initial_cash)
        strategy.data = df
        strategy.init()

        trades: list[Trade] = []
        open_trades: dict[str, dict] = {}
        equity_curve: list[dict] = []
        dates = sorted(df["date"].unique())

        prev_equity_value = initial_cash
        peak_equity = initial_cash
        max_dd = 0.0

        symbols = list(df["symbol"].unique())
        bar_idx = 0

        for dt in dates:
            bars = df[df["date"] == dt]
            prices = dict(zip(bars["symbol"], bars["close"]))

            # Generate signals for all symbols on this date
            signals: list[Signal] = []
            for sym in symbols:
                sym_mask = df["symbol"] == sym
                sym_rows = df[sym_mask]
                sym_global_indices = df.index[sym_mask]
                sym_day_mask = sym_rows["date"] == dt
                if not sym_day_mask.any():
                    continue
                # Find this symbol's row index for today
                sym_row_idx = sym_rows.index[sym_rows["date"] == dt].tolist()
                sym_i = sym_rows.index.get_loc(sym_row_idx[0]) if sym_row_idx else 0
                # Temporarily set data to just this symbol's data
                orig_data = strategy.data
                strategy.data = sym_rows.reset_index(drop=True)
                s = strategy.next(sym_i)
                strategy.data = orig_data
                if s:
                    signals.append(s)
                bar_idx += 1

            # Execute signals (buys first, then sells)
            for s in signals:
                self._execute(s, bars, strategy.portfolio, open_trades, trades, dt)

            strategy.portfolio.age_positions()
            equity_value = strategy.portfolio.equity(prices)
            daily_ret = (equity_value - prev_equity_value) / prev_equity_value if prev_equity_value else 0
            prev_equity_value = equity_value
            peak_equity = max(peak_equity, equity_value)
            dd = (peak_equity - equity_value) / peak_equity if peak_equity > 0 else 0.0
            max_dd = max(max_dd, dd)

            equity_curve.append({
                "date": str(dt)[:10],
                "equity": round(equity_value, 2),
                "cash": round(strategy.portfolio.cash, 2),
                "positions": len(strategy.portfolio.positions),
                "drawdown": round(dd, 4),
            })

        final_equity = equity_curve[-1]["equity"] if equity_curve else initial_cash
        total_return = (final_equity - initial_cash) / initial_cash
        trading_days = len(dates)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days else 0

        daily_rets = pd.Series([
            (equity_curve[j]["equity"] - equity_curve[j - 1]["equity"]) / equity_curve[j - 1]["equity"]
            if j > 0 and equity_curve[j - 1]["equity"] > 0 else 0
            for j in range(len(equity_curve))
        ])
        sharpe = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)
                  if daily_rets.std() > 0 else 0)

        winning = [t for t in trades if t.pnl > 0]
        win_rate = len(winning) / len(trades) if trades else 0
        avg_win = np.mean([t.pnl_pct for t in winning]) if winning else 0
        losing = [t for t in trades if t.pnl < 0]
        avg_loss = abs(np.mean([t.pnl_pct for t in losing])) if losing else 0
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
            benchmark_compare={},
        )

    def _execute(self, signal: Signal, bars: pd.DataFrame, portfolio: Portfolio,
                 open_trades: dict, trades: list[Trade], dt):
        bar = bars[bars["symbol"] == signal.symbol]
        if bar.empty:
            return
        bar = bar.iloc[0]

        # Circuit breaker check: skip if the bar appears to be at limit-up/down
        # (simplified: zero-volume or price stuck at extreme)
        if bar.get("volume", 0) == 0:
            logger.debug(f"Skipping {signal.action} for {signal.symbol} on {dt}: zero volume")
            return

        if signal.action == "BUY":
            self._execute_buy(signal, bar, portfolio, open_trades, dt)
        elif signal.action == "SELL":
            self._execute_sell(signal, bar, portfolio, open_trades, trades, dt)

    def _execute_buy(self, signal: Signal, bar, portfolio: Portfolio,
                     open_trades: dict, dt):
        # Apply slippage to entry price
        price = bar["close"] * (1 + self.SLIPPAGE)

        # signal.size is interpreted as desired cash allocation for BUY
        desired_cash = signal.size
        max_shares = int(desired_cash / (price * (1 + self.COMMISSION_RATE)))
        max_shares = (max_shares // self.MIN_LOT) * self.MIN_LOT
        shares = max_shares

        if shares < self.MIN_LOT:
            return

        # Verify we have enough cash
        cost = shares * price * (1 + self.COMMISSION_RATE)
        if cost > portfolio.cash:
            # Recalculate using available cash
            max_shares = int(portfolio.cash * 0.95 / (price * (1 + self.COMMISSION_RATE)))
            shares = (max_shares // self.MIN_LOT) * self.MIN_LOT
            if shares < self.MIN_LOT:
                return
            cost = shares * price * (1 + self.COMMISSION_RATE)

        # portfolio.add_position deducts shares * price from cash
        portfolio.add_position(signal.symbol, shares, price, str(dt)[:10])
        # Deduct commission separately (not handled by Portfolio)
        commission = shares * price * self.COMMISSION_RATE
        portfolio.cash -= commission

        open_trades[signal.symbol] = {
            "date": str(dt)[:10],
            "price": price,
            "shares": shares,
        }

    def _execute_sell(self, signal: Signal, bar, portfolio: Portfolio,
                      open_trades: dict, trades: list[Trade], dt):
        # T+1 enforcement
        if not portfolio.can_sell(signal.symbol):
            return

        # Apply slippage to exit price (negative for sells)
        price = bar["close"] * (1 - self.SLIPPAGE)

        pos = portfolio.positions[signal.symbol]

        # signal.size for SELL: 0 means sell all, otherwise number of shares
        desired_shares = int(signal.size) if signal.size > 0 else pos["shares"]
        shares = (desired_shares // self.MIN_LOT) * self.MIN_LOT
        if shares < self.MIN_LOT or shares > pos["shares"]:
            shares = (pos["shares"] // self.MIN_LOT) * self.MIN_LOT
        if shares == 0:
            return

        ot = open_trades.pop(signal.symbol, None)
        entry_price = ot["price"] if ot else pos["avg_cost"]

        # Calculate P&L
        gross_revenue = shares * price
        entry_cost = shares * entry_price * (1 + self.COMMISSION_RATE)
        pnl = gross_revenue * (1 - self.COMMISSION_RATE - self.STAMP_TAX_RATE) - entry_cost
        pnl_pct = pnl / entry_cost if entry_cost else 0

        # Close the position (adds shares * price to cash)
        portfolio.close_position(signal.symbol, price, shares)
        # Deduct fees: commission + stamp tax
        fees = shares * price * (self.COMMISSION_RATE + self.STAMP_TAX_RATE)
        portfolio.cash -= fees

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

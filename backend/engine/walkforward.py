"""Walk-forward optimization framework.

Implements anchored walk-forward: train on expanding window,
validate on subsequent out-of-sample period.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Type

import numpy as np
import pandas as pd
from loguru import logger

from backend.engine.backtest import BacktestEngine, BacktestResult
from backend.engine.strategy import BaseStrategy
from backend.storage.cleaner import load_bulk


@dataclass
class WFWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict
    train_sharpe: float
    test_result: BacktestResult


@dataclass
class WFRResult:
    windows: list[WFWindow]
    oos_return: float
    oos_sharpe: float
    oos_max_dd: float
    oos_win_rate: float
    param_stability: dict  # param -> [values across windows]
    consolidated_trades: list
    consolidated_equity: list


class WalkForwardOptimizer:

    def __init__(self, engine: BacktestEngine = None):
        self.engine = engine or BacktestEngine()

    def run(
        self,
        strategy_cls: Type[BaseStrategy],
        param_grid: dict[str, list],
        universe: list[str],
        train_start: str,
        train_end: str,
        test_windows: list[tuple[str, str]],  # [(test_start, test_end), ...]
        anchor: str = "expanding",  # "expanding" or "rolling"
        rolling_years: int = 2,
    ) -> WFRResult:
        """
        Anchored walk-forward:
        - Window 1: train [train_start, train_end], test [test1_start, test1_end]
        - Window 2: train [train_start, test1_end], test [test2_start, test2_end]
        - ...
        """
        windows = []
        all_trades = []
        all_equity = []
        param_history = {}

        current_train_end = train_end
        oos_total_return = 1.0

        all_data = load_bulk(universe, train_start, test_windows[-1][1])
        if all_data.empty:
            raise ValueError("No data for the given universe and date range")

        for wi, (test_start, test_end) in enumerate(test_windows):
            logger.info(f"Walk-forward window {wi+1}/{len(test_windows)}: "
                        f"train=[{train_start}, {current_train_end}] test=[{test_start}, {test_end}]")

            # Grid search on training period
            best_params, best_sharpe = self._grid_search(
                strategy_cls, param_grid, universe,
                train_start, current_train_end
            )

            # Test on out-of-sample
            test_result = self.engine.run(
                strategy_cls, test_start, test_end, universe,
                params=best_params
            )

            window = WFWindow(
                train_start=train_start,
                train_end=current_train_end,
                test_start=test_start,
                test_end=test_end,
                best_params=best_params.copy(),
                train_sharpe=round(best_sharpe, 4),
                test_result=test_result,
            )
            windows.append(window)

            all_trades.extend(test_result.trades)
            all_equity.extend(test_result.daily_equity)

            oos_total_return *= (1 + test_result.total_return)
            logger.info(f"  Best params: {best_params} Train Sharpe: {best_sharpe:.2f} "
                        f"OOS Return: {test_result.total_return:.2%}")

            # Track param stability
            for k, v in best_params.items():
                param_history.setdefault(k, []).append(v)

            # Expand or roll the train window
            if anchor == "expanding":
                current_train_end = test_end
            else:
                train_start_dt = pd.Timestamp(test_end) - pd.DateOffset(years=rolling_years)
                train_start = train_start_dt.strftime("%Y-%m-%d")
                current_train_end = test_end

        # Compute consolidated metrics
        all_trades_sorted = sorted(all_trades, key=lambda t: t.exit_date)
        winning = [t for t in all_trades_sorted if t.pnl > 0]
        oos_win_rate = len(winning) / len(all_trades_sorted) if all_trades_sorted else 0

        oos_annual_return = oos_total_return ** (1 / len(test_windows)) - 1 if test_windows else 0

        param_stability = {}
        for k, vals in param_history.items():
            vals_arr = np.array(vals)
            param_stability[k] = {
                "values": [int(v) if isinstance(v, (np.integer,)) else v for v in vals],
                "mean": float(np.mean(vals_arr)),
                "std": float(np.std(vals_arr)),
                "cv": float(np.std(vals_arr) / np.mean(vals_arr)) if np.mean(vals_arr) != 0 else 0,
            }

        return WFRResult(
            windows=windows,
            oos_return=round(oos_total_return - 1, 4),
            oos_sharpe=round(
                np.mean([w.test_result.sharpe_ratio for w in windows])
                if windows else 0, 4
            ),
            oos_max_dd=round(
                max(w.test_result.max_drawdown for w in windows)
                if windows else 0, 4
            ),
            oos_win_rate=round(oos_win_rate, 4),
            param_stability=param_stability,
            consolidated_trades=all_trades_sorted,
            consolidated_equity=all_equity,
        )

    def _grid_search(self, strategy_cls, param_grid, universe, train_start, train_end):
        """Brute-force grid search maximizing Sharpe ratio.

        Filters invalid param combinations (fast >= slow) and penalizes
        zero-trade results to prevent overfitting to no-signal regimes.
        """
        best_params = {}
        best_score = -999

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        def _is_valid(params):
            if "fast" in params and "slow" in params:
                if params["fast"] >= params["slow"]:
                    return False
            return True

        def _recurse(idx, current):
            nonlocal best_params, best_score
            if idx == len(keys):
                if not _is_valid(current):
                    return
                try:
                    result = self.engine.run(
                        strategy_cls, train_start, train_end,
                        universe, params=current.copy()
                    )
                    if len(result.trades) == 0:
                        score = -999
                    else:
                        score = result.sharpe_ratio
                    if score > best_score:
                        best_score = score
                        best_params = current.copy()
                except Exception:
                    pass
                return
            for v in values[idx]:
                current[keys[idx]] = v
                _recurse(idx + 1, current)

        _recurse(0, {})
        return best_params, best_score

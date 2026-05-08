"""Optuna-based strategy parameter optimization."""
import optuna
from loguru import logger

from backend.engine.backtest import BacktestEngine
from backend.engine.strategy import BaseStrategy

optuna.logging.set_verbosity(optuna.logging.WARNING)


class StrategyOptimizer:
    def __init__(self, n_trials: int = 100):
        self.n_trials = n_trials
        self.engine = BacktestEngine()

    def optimize(
        self,
        strategy_cls: type[BaseStrategy],
        param_ranges: dict,
        universe: list[str],
        start_date: str,
        end_date: str,
        validation_start: str,
        validation_end: str,
    ) -> dict:
        def objective(trial):
            params = {}
            for name, (low, high, dtype) in param_ranges.items():
                if dtype == "int":
                    params[name] = trial.suggest_int(name, low, high)
                elif dtype == "float":
                    params[name] = trial.suggest_float(name, low, high)

            try:
                val_result = self.engine.run(
                    strategy_cls, validation_start, validation_end,
                    universe, params=params
                )
                return val_result.sharpe_ratio
            except Exception as e:
                logger.warning(f"Trial failed: {e}")
                return -999.0

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)

        best = study.best_params
        best_result = self.engine.run(strategy_cls, start_date, validation_end, universe, params=best)

        stability = self._check_stability(strategy_cls, best, param_ranges, universe,
                                          start_date, validation_end)

        return {
            "best_params": best,
            "best_value": round(study.best_value, 4),
            "best_result": {
                "total_return": best_result.total_return,
                "sharpe_ratio": best_result.sharpe_ratio,
                "max_drawdown": best_result.max_drawdown,
            },
            "n_trials": len(study.trials),
            "stability": stability,
        }

    def _check_stability(self, strategy_cls, best_params, param_ranges,
                         universe, start, end) -> dict:
        results = {}
        for name in best_params:
            perturbed = []
            for pct in [-0.1, 0, 0.1]:
                val = best_params[name] * (1 + pct)
                if name in param_ranges:
                    low, high, dtype = param_ranges[name]
                    if dtype == "int":
                        val = int(round(val))
                    val = max(low, min(high, val))
                try:
                    r = self.engine.run(strategy_cls, start, end, universe, params={**best_params, name: val})
                    perturbed.append({"perturbation": f"{pct:+.0%}", "sharpe": round(r.sharpe_ratio, 4)})
                except Exception as e:
                    perturbed.append({"perturbation": f"{pct:+.0%}", "error": str(e)})
            results[name] = perturbed
        return results

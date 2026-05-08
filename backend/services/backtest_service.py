"""Backtest job management."""
import importlib
from typing import Type

from backend.engine.backtest import BacktestEngine, BacktestResult
from backend.engine.strategy import BaseStrategy
from backend.storage.db import get_conn

_engine = BacktestEngine()
_results: dict[str, BacktestResult] = {}

def _load_strategy(class_path: str) -> Type[BaseStrategy]:
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)

def run_backtest(strategy_id: str, start_date: str, end_date: str,
                 universe: list[str], initial_cash: float, params: dict) -> BacktestResult:
    from backend.services.strategy_service import _TEMPLATES
    if strategy_id not in _TEMPLATES:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    template = _TEMPLATES[strategy_id]
    strategy_cls = _load_strategy(template["class"])
    merged_params = {**template["params"], **params}
    result = _engine.run(strategy_cls, start_date, end_date, universe, initial_cash, params=merged_params)
    _results[result.id] = result
    conn = get_conn()
    conn.execute(
        "INSERT INTO backtest_results (id, strategy_name, params, start_date, end_date, universe, metrics) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (result.id, strategy_id, str(merged_params), start_date, end_date,
         ",".join(universe), str({"total_return": result.total_return}))
    )
    conn.commit()
    return result

def get_result(result_id: str) -> BacktestResult:
    if result_id not in _results:
        raise KeyError(f"Result {result_id} not found")
    return _results[result_id]

"""Strategy template management."""
import importlib

_TEMPLATES = {
    "ma_crossover": {
        "name": "均线交叉",
        "class": "backend.strategies.macross.MACrossover",
        "params": {"fast": 5, "slow": 20},
        "description": "快线上穿慢线买入，下穿卖出。适合趋势行情"
    },
    "trend_momentum": {
        "name": "趋势动量(多因子)",
        "class": "backend.strategies.trend_momentum.TrendMomentum",
        "params": {
            "fast": 10, "slow": 30, "trend": 60,
            "rsi_period": 14, "rsi_low": 35, "rsi_high": 65,
            "vol_period": 20, "atr_period": 14,
            "risk_pct": 0.02, "stop_atr_mult": 2.0
        },
        "description": "EMA交叉+RSI过滤+成交量确认+ATR动态止损，适合稳健趋势跟踪"
    },
}

def list_templates() -> list[dict]:
    return [
        {"id": k, "name": v["name"], "params": v["params"], "description": v["description"]}
        for k, v in _TEMPLATES.items()
    ]

def validate_strategy(strategy_id: str, params: dict) -> dict:
    if strategy_id not in _TEMPLATES:
        return {"valid": False, "error": f"Unknown strategy: {strategy_id}"}
    return {"valid": True, "strategy": _TEMPLATES[strategy_id]["name"]}

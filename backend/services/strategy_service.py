"""Strategy template management."""
import importlib

_TEMPLATES = {
    "ma_crossover": {
        "name": "均线交叉",
        "class": "backend.strategies.macross.MACrossover",
        "params": {"fast": 5, "slow": 20},
        "description": "快线上穿慢线买入，下穿卖出"
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

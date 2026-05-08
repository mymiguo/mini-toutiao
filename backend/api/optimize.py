from fastapi import APIRouter

router = APIRouter(prefix="/api/optimize", tags=["optimize"])

@router.post("/run")
async def run_optimize(req: dict):
    import importlib
    from backend.engine.optimizer import StrategyOptimizer
    from backend.services.strategy_service import _TEMPLATES

    strategy_id = req["strategy_id"]
    template = _TEMPLATES[strategy_id]
    mod_path, cls_name = template["class"].rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    strategy_cls = getattr(mod, cls_name)

    opt = StrategyOptimizer(n_trials=req.get("n_trials", 50))
    result = opt.optimize(
        strategy_cls=strategy_cls,
        param_ranges=req["param_ranges"],
        universe=req["universe"],
        start_date=req["start_date"],
        end_date=req["end_date"],
        validation_start=req["validation_start"],
        validation_end=req["validation_end"],
    )
    return result

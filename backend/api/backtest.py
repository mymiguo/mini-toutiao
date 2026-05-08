from fastapi import APIRouter
from backend.services.backtest_service import run_backtest, get_result, _results

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

@router.post("/run")
async def run(req: dict):
    result = run_backtest(
        strategy_id=req["strategy_id"],
        start_date=req["start_date"],
        end_date=req["end_date"],
        universe=req["universe"],
        initial_cash=req.get("initial_cash", 100000),
        params=req.get("params", {}),
    )
    return {
        "id": result.id,
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "profit_loss_ratio": result.profit_loss_ratio,
        "trade_count": len(result.trades),
    }

@router.get("/result/{result_id}")
async def result_detail(result_id: str):
    r = get_result(result_id)
    return {
        "id": r.id,
        "total_return": r.total_return,
        "annual_return": r.annual_return,
        "max_drawdown": r.max_drawdown,
        "sharpe_ratio": r.sharpe_ratio,
        "win_rate": r.win_rate,
        "profit_loss_ratio": r.profit_loss_ratio,
        "trades": [t.__dict__ for t in r.trades],
        "daily_equity": r.daily_equity,
    }

@router.get("/results")
async def results_list():
    return list(_results.keys())

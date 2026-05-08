from fastapi import APIRouter
from backend.services.strategy_service import list_templates, validate_strategy

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

@router.get("/templates")
async def templates():
    return list_templates()

@router.post("/validate")
async def validate(req: dict):
    return validate_strategy(req.get("strategy_id", ""), req.get("params", {}))

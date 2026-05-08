from fastapi import APIRouter
from backend.services.sentiment_service import get_current_sentiment, get_sentiment_history

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

@router.get("/current")
async def current():
    return await get_current_sentiment()

@router.get("/history")
async def history(start: str, end: str):
    return await get_sentiment_history(start, end)

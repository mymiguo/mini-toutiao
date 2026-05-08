"""Data REST API endpoints."""
from fastapi import APIRouter

from backend.models import DownloadRequest
from backend.services.data_service import (
    download_daily,
    get_download_status,
    get_stock_list,
    refresh_stock_list,
    get_daily,
    get_financials,
)
from backend.storage.cleaner import get_latest_date

router = APIRouter(prefix="/api/data", tags=["data"])

@router.get("/stocks")
async def stocks():
    return get_stock_list()

@router.post("/stocks/refresh")
async def refresh():
    count = refresh_stock_list()
    return {"count": count}

@router.get("/daily/{symbol}")
async def daily(symbol: str, start: str = None, end: str = None):
    data = get_daily(symbol, start, end)
    return {"symbol": symbol, "count": len(data), "data": data}

@router.get("/latest/{symbol}")
async def latest_date(symbol: str):
    d = get_latest_date(symbol)
    return {"symbol": symbol, "latest_date": d}

@router.post("/download")
async def download(req: DownloadRequest):
    task_id = await download_daily(req.symbols, req.start_date, req.end_date)
    return {"task_id": task_id}

@router.get("/download/status/{task_id}")
async def download_status(task_id: str):
    return get_download_status(task_id)

@router.get("/financials/{symbol}")
async def financials(symbol: str):
    return get_financials(symbol)

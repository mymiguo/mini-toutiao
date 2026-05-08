"""FastAPI application entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from backend.api.data import router as data_router
from backend.api.strategy import router as strategy_router
from backend.api.backtest import router as backtest_router
from backend.api.optimize import router as optimize_router
from backend.api.sentiment import router as sentiment_router
from backend.config import ensure_dirs
from backend.storage.db import init_schema

app = FastAPI(title="A股交易工具", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router)
app.include_router(strategy_router)
app.include_router(backtest_router)
app.include_router(optimize_router)
app.include_router(sentiment_router)

@app.on_event("startup")
async def startup():
    ensure_dirs()
    init_schema()
    logger.info("Backend started on :8765")

@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": type(exc).__name__, "detail": str(exc)}
    )

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

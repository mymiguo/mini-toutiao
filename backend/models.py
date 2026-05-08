"""Shared Pydantic models."""
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    error: str
    detail: str

class DownloadRequest(BaseModel):
    symbols: list[str]
    start_date: str
    end_date: str

class DownloadStatus(BaseModel):
    task_id: str
    status: str
    done: int
    total: int
    errors: list[dict]

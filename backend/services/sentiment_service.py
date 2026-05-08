"""Sentiment data service with caching."""
from datetime import datetime

import pandas as pd
from backend.engine.sentiment import compute_sentiment

_cache: dict[str, dict] = {}

async def get_current_sentiment() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in _cache:
        _cache[today] = await compute_sentiment(today)
    return _cache[today]

async def get_sentiment_history(start: str, end: str) -> list[dict]:
    results = []
    current = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while current <= end_ts:
        d = current.strftime("%Y-%m-%d")
        if d in _cache:
            results.append(_cache[d])
        else:
            try:
                r = await compute_sentiment(d)
                _cache[d] = r
                results.append(r)
            except Exception:
                pass
        current += pd.Timedelta(days=1)
    return results

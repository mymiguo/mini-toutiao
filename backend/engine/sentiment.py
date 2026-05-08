"""Market sentiment scoring engine based on 5 factors."""
from datetime import datetime

import pandas as pd
from loguru import logger

from backend.storage.fetcher import fetch_dragon_tiger
from backend.storage.cleaner import load_cleaned

DEFAULT_WEIGHTS = {
    "money_flow": 0.20,
    "dragon_tiger": 0.20,
    "limit_ratio": 0.20,
    "volume_deviation": 0.20,
    "margin_balance": 0.20,
}


async def compute_sentiment(date: str = None) -> dict:
    """Compute composite sentiment score for a given date (YYYY-MM-DD)."""
    d = date or datetime.now().strftime("%Y-%m-%d")

    scores = {}

    # 1. 龙虎榜活跃度
    try:
        dragon_df = await fetch_dragon_tiger(d.replace("-", ""))
        scores["dragon_tiger"] = min(len(dragon_df) / 20 * 100, 100) if not dragon_df.empty else 50
    except Exception as e:
        logger.warning(f"Dragon tiger fetch failed: {e}")
        scores["dragon_tiger"] = 50

    # 2. 涨跌停家数比 (sampled from representative stocks)
    try:
        sample_symbols = ["000001", "000002", "600000", "600036", "601318"]
        up_count = 0
        total = 0
        for sym in sample_symbols:
            df = load_cleaned(sym, None, d)
            if len(df) >= 2:
                total += 1
                if df["close"].iloc[-1] > df["close"].iloc[-2]:
                    up_count += 1
        scores["limit_ratio"] = (up_count / total * 100) if total > 0 else 50
    except Exception:
        scores["limit_ratio"] = 50

    # 3. 成交额偏离度
    try:
        sample_symbols = ["000001", "000002", "600000", "600036"]
        df = pd.DataFrame()
        for sym in sample_symbols:
            sym_df = load_cleaned(sym, None, d)
            if len(sym_df) >= 20:
                recent_vol = sym_df["amount"].iloc[-20:]
                avg_vol = recent_vol.mean()
                if avg_vol > 0:
                    deviation = (recent_vol.iloc[-1] / avg_vol - 1) * 100
                    scores["volume_deviation"] = max(0, min(100, deviation + 50))
                else:
                    scores["volume_deviation"] = 50
                break
        else:
            scores["volume_deviation"] = 50
    except Exception:
        scores["volume_deviation"] = 50

    # 4. 融资融券 (requires margin data, use neutral default for now)
    scores["margin_balance"] = 50

    # 5. 资金流方向 (requires fund flow data, use neutral default for now)
    scores["money_flow"] = 50

    composite = sum(scores.get(k, 50) * DEFAULT_WEIGHTS.get(k, 0.2) for k in DEFAULT_WEIGHTS)

    return {
        "date": d,
        "composite": round(composite, 1),
        "components": {k: round(v, 1) for k, v in scores.items()},
        "interpretation": _interpret(composite),
    }


def _interpret(score: float) -> str:
    if score >= 80:
        return "极度乐观"
    elif score >= 60:
        return "偏乐观"
    elif score >= 40:
        return "中性"
    elif score >= 20:
        return "偏悲观"
    return "极度悲观"

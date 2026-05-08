"""Base strategy class and Signal definition."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd


@dataclass
class Signal:
    symbol: str
    action: Literal["BUY", "SELL"]
    size: float
    price_type: Literal["open", "close", "limit"] = "close"
    limit_price: Optional[float] = None


class Portfolio:
    """Tracks current positions and cash during backtest."""
    def __init__(self, initial_cash: float = 100_000):
        self.cash = initial_cash
        self.positions: dict[str, dict] = {}
        self.pending_buys: list[Signal] = []

    def can_sell(self, symbol: str) -> bool:
        pos = self.positions.get(symbol)
        return pos is not None and pos["shares"] > 0 and pos["hold_days"] > 0

    def add_position(self, symbol: str, shares: int, price: float, date: str):
        self.positions[symbol] = {"shares": shares, "avg_cost": price, "date": date, "hold_days": 0}
        self.cash -= shares * price

    def close_position(self, symbol: str, price: float, shares: int = None):
        pos = self.positions[symbol]
        sold = shares or pos["shares"]
        self.cash += sold * price
        if shares is None or shares >= pos["shares"]:
            del self.positions[symbol]
        else:
            pos["shares"] -= shares

    def age_positions(self):
        for p in self.positions.values():
            p["hold_days"] += 1

    def equity(self, prices: dict[str, float]) -> float:
        pos_value = sum(
            self.positions[s]["shares"] * prices.get(s, 0)
            for s in self.positions
        )
        return self.cash + pos_value


class BaseStrategy(ABC):
    """Strategy base class. Subclass and implement init() and next()."""

    def __init__(self, params: dict = None):
        self.params = params or {}
        self.portfolio: Optional[Portfolio] = None
        self.data: Optional[pd.DataFrame] = None
        self.indicators: dict = {}

    @abstractmethod
    def init(self):
        """Calculate indicators once. self.data is available."""
        ...

    @abstractmethod
    def next(self, i: int) -> Optional[Signal]:
        """Called on each bar. Return Signal or None."""
        ...

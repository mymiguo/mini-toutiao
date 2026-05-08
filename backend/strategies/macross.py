"""Sample MA crossover strategy."""
import pandas as pd
from backend.engine.strategy import BaseStrategy, Signal
from backend.engine.indicators import sma, cross_over, cross_under


class MACrossover(BaseStrategy):
    def init(self):
        close = self.data.groupby("symbol")["close"]
        self.fast = close.transform(lambda x: sma(x, self.params.get("fast", 5)))
        self.slow = close.transform(lambda x: sma(x, self.params.get("slow", 20)))

    def next(self, i: int) -> Signal | None:
        symbol = self.data["symbol"].iloc[i]
        pf = self.portfolio
        if cross_over(self.fast, self.slow, i):
            return Signal(symbol=symbol, action="BUY", size=pf.cash * 0.3)
        elif cross_under(self.fast, self.slow, i):
            return Signal(symbol=symbol, action="SELL", size=0)
        return None

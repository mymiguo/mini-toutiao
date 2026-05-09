"""Risk management layer.

Position sizing based on:
  - Kelly criterion (adjusted for estimation error)
  - Volatility targeting (equalize risk contribution)
  - Maximum drawdown control
  - Sector/industry concentration limits
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class PositionSize:
    shares: int
    risk_pct: float  # % of portfolio at risk
    stop_price: float
    reason: str


class RiskManager:
    """Dynamic position sizing and risk control.

    Parameters:
        max_position_pct: max single position as % of portfolio (default 20%)
        max_sector_pct: max sector exposure (default 40%)
        vol_target: annualized volatility target (default 15%)
        max_drawdown_limit: hard stop at this drawdown level (default 25%)
        kelly_fraction: fraction of Kelly to use (default 0.25, "half-Kelly" is 0.5)
    """

    def __init__(
        self,
        max_position_pct: float = 0.20,
        max_sector_pct: float = 0.40,
        vol_target: float = 0.15,
        max_drawdown_limit: float = 0.25,
        kelly_fraction: float = 0.25,
    ):
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.vol_target = vol_target
        self.max_drawdown_limit = max_drawdown_limit
        self.kelly_fraction = kelly_fraction
        self.sector_exposure: dict[str, float] = {}
        self.current_drawdown: float = 0.0

    def size_position(
        self,
        portfolio_value: float,
        price: float,
        signal_strength: float,
        atr: Optional[float] = None,
        win_rate: float = 0.50,
        avg_win_loss_ratio: float = 2.0,
        sector: str = "unknown",
    ) -> PositionSize:
        """Calculate optimal position size.

        Uses modified Kelly: f* = win_rate - (1-win_rate) / win_loss_ratio
        Then applies Kelly fraction and additional risk constraints.
        """
        if signal_strength == 0 or price <= 0:
            return PositionSize(0, 0.0, 0.0, "no signal")

        # 1. Kelly-optimized risk allocation (with NaN guards)
        try:
            if pd.notna(win_rate) and pd.notna(avg_win_loss_ratio) and win_rate > 0 and avg_win_loss_ratio > 0:
                kelly_f = win_rate - (1 - win_rate) / avg_win_loss_ratio
                kelly_f = max(0.01, min(float(kelly_f), 0.25))
            else:
                kelly_f = 0.05
        except (ValueError, ZeroDivisionError):
            kelly_f = 0.05

        risk_pct = float(kelly_f) * self.kelly_fraction * abs(signal_strength)

        # 2. Volatility targeting adjustment (with NaN guard)
        try:
            if atr is not None and pd.notna(atr) and float(atr) > 0 and price > 0:
                daily_vol = float(atr) / price
                annual_vol = daily_vol * np.sqrt(252)
                if annual_vol > 0:
                    vol_scalar = min(self.vol_target / annual_vol, 1.5)
                    risk_pct *= vol_scalar
        except (ValueError, TypeError, ZeroDivisionError):
            pass

        # 3. Max position cap
        risk_pct = min(risk_pct, self.max_position_pct)

        # 4. Sector concentration check
        current_sector_pct = self.sector_exposure.get(sector, 0.0)
        remaining_sector = self.max_sector_pct - current_sector_pct
        risk_pct = min(risk_pct, remaining_sector)

        # 5. Drawdown circuit breaker
        if self.current_drawdown > self.max_drawdown_limit * 0.7:
            risk_pct *= 0.5  # Half size after 70% of max DD
        if self.current_drawdown > self.max_drawdown_limit:
            return PositionSize(0, 0.0, 0.0, "dd limit")

        # 6. Calculate shares (round to 100-share lots)
        try:
            capital_at_risk = float(portfolio_value) * float(risk_pct)
            stop_distance = float(price) * 0.05
            if atr is not None and pd.notna(atr) and float(atr) > 0:
                stop_distance = float(atr) * 2.0
            stop_distance = max(stop_distance, float(price) * 0.02)
            shares = int(capital_at_risk / stop_distance / 100) * 100
            max_shares = int(portfolio_value * risk_pct / price / 100) * 100
            shares = max(0, min(shares, max_shares))
        except (ValueError, TypeError, ZeroDivisionError):
            shares = 0

        shares = max(0, shares)  # ensure non-negative

        stop_price = round(price - atr * 2.0, 2) if (atr is not None and pd.notna(atr)) else round(price * 0.95, 2)

        return PositionSize(
            shares=shares,
            risk_pct=round(risk_pct, 4),
            stop_price=stop_price,
            reason=f"Kelly={kelly_f:.1%} vol_adj={vol_scalar if atr else 1.0:.1f}x"
        )

    def update_drawdown(self, current_dd: float):
        self.current_drawdown = current_dd

    def update_sector_exposure(self, positions: dict[str, dict], sector_map: dict[str, str],
                                portfolio_value: float, prices: dict[str, float]):
        """Update per-sector exposure from current positions."""
        self.sector_exposure.clear()
        for sym, pos in positions.items():
            sector = sector_map.get(sym, "unknown")
            pos_value = pos["shares"] * prices.get(sym, 0)
            self.sector_exposure[sector] = self.sector_exposure.get(sector, 0) + pos_value / portfolio_value

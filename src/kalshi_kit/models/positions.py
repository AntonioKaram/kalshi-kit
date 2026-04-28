from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Position(BaseModel):
    market_ticker: str
    yes_contracts: int = 0
    no_contracts: int = 0
    average_yes_price: float | None = None
    average_no_price: float | None = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    updated_at: datetime


class PnLSnapshot(BaseModel):
    ts: datetime
    realized_pnl: float
    unrealized_pnl: float
    gross_exposure: float
    net_exposure: float
    session_id: str

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FillRecord(BaseModel):
    fill_id: str
    order_id: str
    client_order_id: str | None = None
    market_ticker: str
    side: str
    action: str
    price: float
    size: int
    fee: float
    liquidity: str
    ts: datetime
    session_id: str

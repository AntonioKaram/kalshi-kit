from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

OrderSide = Literal["yes", "no"]
OrderAction = Literal["buy", "sell"]
OrderStatus = Literal["new", "resting", "partially_filled", "filled", "canceled", "rejected"]


class OrderRequest(BaseModel):
    market_ticker: str
    side: OrderSide
    action: OrderAction
    price: float
    size: int
    post_only: bool = True
    reduce_only: bool = False
    client_order_id: str
    trace_id: str
    session_id: str
    created_at: datetime


class OrderRecord(BaseModel):
    order_id: str
    client_order_id: str
    market_ticker: str
    side: OrderSide
    action: OrderAction
    status: OrderStatus
    price: float
    size: int
    filled_size: int = 0
    remaining_size: int = 0
    average_fill_price: float | None = None
    created_at: datetime
    updated_at: datetime
    broker: str
    session_id: str
    trace_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderStateTransition(BaseModel):
    order_id: str
    from_status: str | None
    to_status: str
    ts: datetime
    reason: str
    session_id: str

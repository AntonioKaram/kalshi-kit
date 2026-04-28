from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MarketMetadata(BaseModel):
    ticker: str
    event_ticker: str | None = None
    title: str
    subtitle: str | None = None
    status: str
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    expiration_time: datetime | None = None
    latest_expiration_time: datetime | None = None
    expected_expiration_time: datetime | None = None
    settlement_ts: datetime | None = None
    strike_type: str | None = None
    floor_strike: float | None = None
    cap_strike: float | None = None
    functional_strike: str | None = None
    rules_primary: str | None = None
    rules_secondary: str | None = None
    can_close_early: bool = False
    tick_size: int | None = None
    market_type: str = "binary"
    response_price_units: str | None = None
    liquidity_dollars: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SpotTick(BaseModel):
    venue: str
    symbol: str
    ts_event: datetime
    ts_received: datetime
    last_price: float
    bid: float | None = None
    ask: float | None = None
    volume: float | None = None

    @property
    def mid(self) -> float:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last_price


class KalshiTicker(BaseModel):
    market_ticker: str
    ts_event: datetime
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    last_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class HealthEvent(BaseModel):
    ts: datetime
    component: str
    status: str
    detail: str
    session_id: str

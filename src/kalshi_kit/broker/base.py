"""Broker Protocol shared by `KalshiBroker` (live) and `PaperBroker`.

Strategies and the replay engine type their broker dependency against this
Protocol so swapping live ↔ paper is a one-line change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.models.orders import OrderRecord, OrderRequest


@runtime_checkable
class Broker(Protocol):
    """Minimum surface a broker must expose.

    Live brokers (`KalshiBroker`) implement `submit_order` / `cancel_order`
    as async network calls. The paper broker uses sync versions because it
    has no network in the loop. Callers should treat both as awaitable for
    forward compatibility (an `await` on a sync return is a no-op).
    """

    def submit_order(self, request: OrderRequest, *args: object, **kwargs: object) -> OrderRecord:
        ...

    def cancel_order(self, order_id: str, *args: object, **kwargs: object) -> OrderRecord | None:
        ...


@runtime_checkable
class PaperLikeBroker(Broker, Protocol):
    """Extension Protocol for brokers that also drive fills from book updates.

    The paper broker fits this; the live broker does not (Kalshi pushes fills
    via WebSocket / REST polling, not from local book deltas).
    """

    def on_book_update(self, book: BinaryOrderBook) -> list[FillRecord]:
        ...


@runtime_checkable
class LiveLikeBroker(Broker, Protocol):
    """Extension Protocol for brokers backed by a live exchange feed."""

    async def sync_orders(self) -> list[OrderRecord]:
        ...

    async def sync_fills(self, *, min_ts: datetime | None = None) -> list[FillRecord]:
        ...

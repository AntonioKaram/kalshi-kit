"""Strategy protocol and base class.

Strategies receive book updates, fills, and tickers, and may submit orders
through their ``self.broker``. Brokers are typed against the
:class:`~kalshi_kit.broker.base.Broker` protocol, so the same strategy code
runs against either :class:`~kalshi_kit.broker.paper.PaperBroker` or
:class:`~kalshi_kit.broker.live.KalshiBroker`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kalshi_kit.broker.base import Broker
from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.market import KalshiTicker
from kalshi_kit.models.orderbook import BinaryOrderBook


@runtime_checkable
class Strategy(Protocol):
    async def on_book_update(self, book: BinaryOrderBook) -> None: ...

    async def on_fill(self, fill: FillRecord) -> None: ...

    async def on_tick(self, ticker: KalshiTicker) -> None: ...

    async def on_kill_switch(self, reason: str) -> None: ...


class BaseStrategy:
    """No-op base class. Subclass and override only the hooks you need."""

    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    async def on_book_update(self, book: BinaryOrderBook) -> None:
        return None

    async def on_fill(self, fill: FillRecord) -> None:
        return None

    async def on_tick(self, ticker: KalshiTicker) -> None:
        return None

    async def on_kill_switch(self, reason: str) -> None:
        return None

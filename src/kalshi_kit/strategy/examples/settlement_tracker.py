"""Read-only strategy that logs top-of-book on every update.

Useful as a smoke test for the WebSocket feed.
"""

from __future__ import annotations

import logging

from kalshi_kit.broker.base import Broker
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.strategy.base import BaseStrategy

logger = logging.getLogger(__name__)


class SettlementTracker(BaseStrategy):
    def __init__(self, broker: Broker, market_ticker: str) -> None:
        super().__init__(broker)
        self.market_ticker = market_ticker

    async def on_book_update(self, book: BinaryOrderBook) -> None:
        if book.market_ticker != self.market_ticker:
            return
        top = book.top_of_book()
        logger.info(
            "settlement_tracker top_of_book ticker=%s yes_bid=%s yes_ask=%s ts=%s",
            self.market_ticker,
            top.yes_bid,
            top.yes_ask,
            book.ts_received.isoformat(),
        )

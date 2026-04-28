"""Educational random-entry strategy.

This strategy has zero economic edge by design and exists only to demonstrate
how to wire a :class:`~kalshi_kit.strategy.base.Strategy` against a broker.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

from kalshi_kit.broker.base import Broker
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.models.orders import OrderRequest
from kalshi_kit.strategy.base import BaseStrategy

try:
    from kalshi_kit.utils.ids import deterministic_order_id
except ImportError:  # pragma: no cover - fallback path
    deterministic_order_id = None  # type: ignore[assignment]


class RandomEntryStrategy(BaseStrategy):
    """Submit a 1-contract YES BUY every Nth book update at a random near-touch price.

    Has zero economic edge by design. Use it as a reference for wiring a
    strategy against a broker; do not deploy it.
    """

    def __init__(
        self,
        broker: Broker,
        market_ticker: str,
        *,
        every_n_updates: int = 20,
        seed: int | None = None,
    ) -> None:
        super().__init__(broker)
        self.market_ticker = market_ticker
        self.every_n_updates = max(1, int(every_n_updates))
        self._rng = random.Random(seed)
        self._update_count = 0

    async def on_book_update(self, book: BinaryOrderBook) -> None:
        self._update_count += 1
        if self._update_count % self.every_n_updates != 0:
            return
        if not book.yes_bids:
            return
        best_yes_bid = book.yes_bids[0].price
        candidate_prices = [best_yes_bid, round(best_yes_bid - 0.01, 2)]
        price = self._rng.choice(candidate_prices)
        if price <= 0.0 or price >= 1.0:
            return

        order_id = self._next_order_id()
        request = OrderRequest(
            client_order_id=order_id,
            market_ticker=self.market_ticker,
            side="yes",
            action="buy",
            price=price,
            size=1,
            post_only=True,
            reduce_only=False,
            created_at=datetime.now(tz=UTC),
        )
        self.broker.submit_order(request, book)

    def _next_order_id(self) -> str:
        if deterministic_order_id is not None:
            try:
                return deterministic_order_id(
                    market_ticker=self.market_ticker,
                    side="yes",
                    action="buy",
                    counter=self._update_count,
                )
            except TypeError:
                return deterministic_order_id(self.market_ticker, self._update_count)
        return uuid.uuid4().hex

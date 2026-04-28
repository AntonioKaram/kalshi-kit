from __future__ import annotations

from dataclasses import dataclass

from kalshi_kit.broker.queue_logic import estimate_queue_position
from kalshi_kit.models.orderbook import BinaryOrderBook


@dataclass(slots=True)
class PassiveFillOutcome:
    filled_size: int
    fill_probability: float


def conservative_passive_fill(
    *,
    book_before: BinaryOrderBook,
    book_after: BinaryOrderBook,
    side: str,
    action: str,
    price: float,
    requested_size: int,
) -> PassiveFillOutcome:
    resting_side, resting_price = _resting_queue_level(side=side, action=action, price=price)
    queue = estimate_queue_position(book_before, side=resting_side, price=resting_price, own_size=requested_size)
    before_levels = book_before.yes_bids if resting_side == "yes" else book_before.no_bids
    after_levels = book_after.yes_bids if resting_side == "yes" else book_after.no_bids
    before_size = next((level.size for level in before_levels if abs(level.price - resting_price) < 1e-9), 0.0)
    after_size = next((level.size for level in after_levels if abs(level.price - resting_price) < 1e-9), 0.0)
    traded_through = max(before_size - after_size, 0.0)
    fillable = max(traded_through - queue.queue_ahead, 0.0)
    filled_size = int(min(requested_size, fillable))
    return PassiveFillOutcome(filled_size=filled_size, fill_probability=queue.fill_probability)


def _resting_queue_level(*, side: str, action: str, price: float) -> tuple[str, float]:
    if action == "buy":
        return side, price
    if side == "yes":
        return "no", max(0.0, 1.0 - price)
    return "yes", max(0.0, 1.0 - price)

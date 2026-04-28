from __future__ import annotations

from dataclasses import dataclass

from kalshi_kit.models.orderbook import BinaryOrderBook


@dataclass(slots=True)
class QueueEstimate:
    queue_ahead: float
    fill_probability: float


def estimate_queue_position(book: BinaryOrderBook, *, side: str, price: float, own_size: int) -> QueueEstimate:
    levels = book.yes_bids if side == "yes" else book.no_bids
    queue_ahead = 0.0
    for level in levels:
        if abs(level.price - price) < 1e-9:
            queue_ahead = level.size
            break
    fill_probability = own_size / max(queue_ahead + own_size, 1.0)
    return QueueEstimate(queue_ahead=queue_ahead, fill_probability=min(fill_probability, 0.95))

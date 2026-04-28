from datetime import UTC, datetime

from kalshi_kit.broker.fill_model import conservative_passive_fill
from kalshi_kit.models.orderbook import BinaryOrderBook


def test_fill_model_respects_queue() -> None:
    before = BinaryOrderBook.from_levels(
        market_ticker="BTC",
        ts_event=datetime.now(tz=UTC),
        ts_received=datetime.now(tz=UTC),
        yes=[(0.45, 0.0)],
        no=[(0.52, 5.0)],
    )
    after = BinaryOrderBook.from_levels(
        market_ticker="BTC",
        ts_event=datetime.now(tz=UTC),
        ts_received=datetime.now(tz=UTC),
        yes=[(0.45, 0.0)],
        no=[(0.60, 1.0)],
    )
    outcome = conservative_passive_fill(
        book_before=before,
        book_after=after,
        side="yes",
        action="buy",
        price=0.45,
        requested_size=1,
    )
    assert outcome.fill_probability >= 0.5

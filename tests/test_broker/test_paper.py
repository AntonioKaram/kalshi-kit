from datetime import UTC, datetime, timedelta

import pytest

from kalshi_kit.broker.paper import PaperBroker
from kalshi_kit.client._config import AppConfig
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.models.orders import OrderRequest
from kalshi_kit.utils.fees import kalshi_taker_fee_dollars


def _book(
    *,
    ts: datetime,
    yes: list[tuple[float, float]],
    no: list[tuple[float, float]],
) -> BinaryOrderBook:
    return BinaryOrderBook.from_levels(
        market_ticker="BTC-TEST",
        ts_event=ts,
        ts_received=ts,
        yes=yes,
        no=no,
    )


def _request(*, ts: datetime, side: str, action: str, price: float) -> OrderRequest:
    return OrderRequest(
        market_ticker="BTC-TEST",
        side=side,
        action=action,
        price=price,
        size=2,
        post_only=True,
        client_order_id=f"{side}-{action}-{int(price * 100)}",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )


@pytest.mark.parametrize(
    ("side", "action", "price"),
    [
        ("yes", "buy", 0.46),
        ("no", "buy", 0.55),
        ("yes", "sell", 0.45),
        ("no", "sell", 0.54),
    ],
)
def test_marketable_post_only_orders_are_rejected(side: str, action: str, price: float) -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    order = broker.submit_order(_request(ts=ts, side=side, action=action, price=price), book)

    assert order.status == "rejected"
    assert order.remaining_size == 0
    assert order.filled_size == 0
    assert order.metadata["post_only"] is True
    assert order.metadata["rejection_reason"] == "post_only_cross"
    assert broker.on_book_update(
        book.model_copy(update={"ts_received": ts + timedelta(seconds=1)})
    ) == []


def test_resting_post_only_order_keeps_maker_fill_path() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    submit_book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    order = broker.submit_order(_request(ts=ts, side="yes", action="buy", price=0.45), submit_book)

    assert order.status == "resting"
    crossed_book = _book(ts=ts + timedelta(seconds=1), yes=[(0.45, 20.0)], no=[(0.55, 20.0)])

    fills = broker.on_book_update(crossed_book)

    assert len(fills) == 1
    assert fills[0].order_id == order.order_id
    assert fills[0].liquidity == "maker"
    # Kalshi charges ceil(7·p·(1-p)) cents per fill regardless of liquidity flag.
    assert fills[0].fee == pytest.approx(kalshi_taker_fee_dollars(order.price) * order.size)
    assert fills[0].size == order.size


def test_taker_buy_fills_at_top_of_book_ask_not_submitted_price() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    # yes_ask = 1 - max(no_bids) = 1 - 0.54 = 0.46
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.50,  # aggressive: above ask, expect fill at ask not at 0.50
        size=2,
        post_only=False,
        client_order_id="taker-buy-aggressive",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    order = broker.submit_order(request, book)
    assert order.status == "resting"

    later = _book(ts=ts + timedelta(milliseconds=200), yes=[(0.45, 20.0)], no=[(0.54, 20.0)])
    fills = broker.on_book_update(later)

    assert len(fills) == 1
    assert fills[0].liquidity == "taker"
    assert fills[0].price == pytest.approx(0.46)
    # Fee charged at fill price (0.46), not submitted price (0.50).
    assert fills[0].fee == pytest.approx(kalshi_taker_fee_dollars(0.46) * fills[0].size)


def test_taker_sell_fills_at_top_of_book_bid_not_submitted_price() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="sell",
        price=0.40,  # conservative: below bid, expect fill at bid (0.45)
        size=2,
        post_only=False,
        client_order_id="taker-sell-conservative",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, book)

    later = _book(ts=ts + timedelta(milliseconds=200), yes=[(0.45, 20.0)], no=[(0.54, 20.0)])
    fills = broker.on_book_update(later)

    assert len(fills) == 1
    assert fills[0].liquidity == "taker"
    assert fills[0].price == pytest.approx(0.45)


def test_taker_buy_size_capped_by_top_of_book_depth() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    # Only 1 contract available at the ask.
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 1.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.50,
        size=5,
        post_only=False,
        client_order_id="taker-buy-deep",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, book)

    later = _book(ts=ts + timedelta(milliseconds=200), yes=[(0.45, 20.0)], no=[(0.54, 1.0)])
    fills = broker.on_book_update(later)

    assert len(fills) == 1
    assert fills[0].size == 1  # capped to ask-side depth


def test_paper_latency_defers_fill_until_book_arrives_after_budget() -> None:
    config = AppConfig()
    assert config.execution.paper_latency_ms == 150  # default sanity
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.50,  # marketable taker
        size=2,
        post_only=False,
        client_order_id="taker-buy-latency",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, book)

    # Same-tick book update: under 150ms from submission, no fill yet.
    same_tick = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])
    assert broker.on_book_update(same_tick) == []

    # 100ms later still under the latency floor: no fill.
    early = _book(ts=ts + timedelta(milliseconds=100), yes=[(0.45, 20.0)], no=[(0.54, 20.0)])
    assert broker.on_book_update(early) == []

    # 200ms later: past the latency budget, fill goes through.
    late = _book(ts=ts + timedelta(milliseconds=200), yes=[(0.45, 20.0)], no=[(0.54, 20.0)])
    fills = broker.on_book_update(late)
    assert len(fills) == 1
    assert fills[0].liquidity == "taker"


def test_paper_latency_sees_moved_book_after_budget() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    initial = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])  # ask = 0.46

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.50,
        size=2,
        post_only=False,
        client_order_id="taker-buy-moved",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, initial)

    # Book moves during the latency window: ask jumps from 0.46 to 0.48.
    moved = _book(
        ts=ts + timedelta(milliseconds=200),
        yes=[(0.45, 20.0)],
        no=[(0.52, 20.0)],  # yes_ask = 1 - 0.52 = 0.48
    )
    fills = broker.on_book_update(moved)
    assert len(fills) == 1
    assert fills[0].price == pytest.approx(0.48)  # filled at the moved ask, not the original 0.46


def test_paper_latency_zero_disables_delay() -> None:
    broker = PaperBroker(paper_latency_ms=0)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.50,
        size=2,
        post_only=False,
        client_order_id="taker-buy-zero-latency",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, book)
    fills = broker.on_book_update(book)
    assert len(fills) == 1


def test_taker_buy_does_not_rest_when_not_marketable() -> None:
    config = AppConfig()
    broker = PaperBroker(config)
    ts = datetime(2026, 4, 15, 12, 0, tzinfo=UTC)
    # ask = 0.46, but order priced at 0.40 (below ask) => not marketable.
    book = _book(ts=ts, yes=[(0.45, 20.0)], no=[(0.54, 20.0)])

    request = OrderRequest(
        market_ticker="BTC-TEST",
        side="yes",
        action="buy",
        price=0.40,
        size=2,
        post_only=False,
        client_order_id="taker-buy-too-cheap",
        trace_id="trace-1",
        session_id="session-1",
        created_at=ts,
    )
    broker.submit_order(request, book)

    # Subsequent book update with same prices: still not marketable, taker should NOT fill passively.
    fills = broker.on_book_update(_book(ts=ts + timedelta(seconds=1), yes=[(0.45, 20.0)], no=[(0.54, 20.0)]))
    assert fills == []

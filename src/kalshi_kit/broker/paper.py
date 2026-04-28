from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kalshi_kit.broker.fill_model import conservative_passive_fill
from kalshi_kit.client._config import AppConfig
from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.models.orders import OrderRecord, OrderRequest
from kalshi_kit.utils.fees import kalshi_taker_fee_dollars


@dataclass(slots=True)
class PaperOrderState:
    order: OrderRecord
    submitted_book: BinaryOrderBook


class PaperBroker:
    """In-memory broker that simulates fills from live orderbook updates.

    Conforms to the same operational shape as `KalshiBroker` (submit / cancel
    / on_book_update). Fills respect post-only crossing rules, queue-position
    estimates, and a configurable latency floor that prevents freshly-submitted
    orders from seeing book updates that arrive faster than network RTT.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        paper_latency_ms: int | None = None,
    ) -> None:
        self.config = config or AppConfig()
        if paper_latency_ms is not None:
            self.config.execution.paper_latency_ms = paper_latency_ms
        self.orders: dict[str, PaperOrderState] = {}
        self.fill_counter = 0

    def submit_order(self, request: OrderRequest, book: BinaryOrderBook) -> OrderRecord:
        crosses_book = _would_cross_book(side=request.side, action=request.action, price=request.price, book=book)
        is_invalid_post_only = request.post_only and crosses_book
        metadata: dict[str, Any] = {
            "post_only": request.post_only,
            "reduce_only": request.reduce_only,
        }
        if is_invalid_post_only:
            metadata["rejection_reason"] = "post_only_cross"
        record = OrderRecord(
            order_id=request.client_order_id,
            client_order_id=request.client_order_id,
            market_ticker=request.market_ticker,
            side=request.side,
            action=request.action,
            status="rejected" if is_invalid_post_only else "resting",
            price=request.price,
            size=request.size,
            filled_size=0,
            remaining_size=0 if is_invalid_post_only else request.size,
            average_fill_price=None,
            created_at=request.created_at,
            updated_at=request.created_at,
            broker="paper",
            session_id=request.session_id,
            trace_id=request.trace_id,
            metadata=metadata,
        )
        self.orders[record.order_id] = PaperOrderState(order=record, submitted_book=book.model_copy(deep=True))
        return record.model_copy(deep=True)

    def cancel_order(self, order_id: str, *, ts: datetime) -> OrderRecord | None:
        state = self.orders.get(order_id)
        if state is None:
            return None
        if state.order.status not in {"resting", "partially_filled"}:
            return state.order.model_copy(deep=True)
        state.order.status = "canceled"
        state.order.updated_at = ts
        return state.order.model_copy(deep=True)

    def on_book_update(self, book: BinaryOrderBook) -> list[FillRecord]:
        fills: list[FillRecord] = []
        latency_ms = max(0, int(self.config.execution.paper_latency_ms))
        for _order_id, state in list(self.orders.items()):
            order = state.order
            if order.market_ticker != book.market_ticker or order.status not in {"resting", "partially_filled"}:
                continue
            # Latency budget: a freshly-submitted order can't see book updates
            # that arrive within `paper_latency_ms` of submission. Real Kalshi
            # round-trip is 50-300ms; default 150 simulates that floor.
            elapsed_ms = (book.ts_received - order.created_at).total_seconds() * 1000.0
            if elapsed_ms < latency_ms:
                continue
            is_post_only = order.metadata.get("post_only", True)
            is_marketable = _would_cross_book(side=order.side, action=order.action, price=order.price, book=book)
            if is_post_only:
                # Maker path: queue-aware passive fill at the resting price. If the
                # book moved through the resting price, treat the order as fully
                # taken (the existing fill-through bypass — preserves prior
                # behavior for resting makers).
                outcome = conservative_passive_fill(
                    book_before=state.submitted_book,
                    book_after=book,
                    side=order.side,
                    action=order.action,
                    price=order.price,
                    requested_size=order.remaining_size,
                )
                fill_size = max(outcome.filled_size, order.remaining_size if is_marketable else 0)
                fill_price = order.price
            elif is_marketable:
                # Taker path: cross the book at the actual offer being lifted, capped
                # by depth at the top of book. Paper used to fill at the order's
                # submitted price, which is optimistic when the strategy submits
                # above the ask (or pessimistic when it submits below the bid for
                # exits). Real Kalshi fills the offer at its quoted price.
                cross = _taker_cross(book=book, side=order.side, action=order.action)
                if cross is None:
                    state.submitted_book = book.model_copy(deep=True)
                    continue
                fill_price, available_size = cross
                fill_size = min(order.remaining_size, int(available_size))
            else:
                # Non-marketable taker — Kalshi would cancel, not rest. Move on.
                state.submitted_book = book.model_copy(deep=True)
                continue
            if fill_size <= 0:
                state.submitted_book = book.model_copy(deep=True)
                continue
            self.fill_counter += 1
            fee_per_contract = kalshi_taker_fee_dollars(fill_price)
            fill = FillRecord(
                fill_id=f"paper-fill-{self.fill_counter}",
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                market_ticker=order.market_ticker,
                side=order.side,
                action=order.action,
                price=fill_price,
                size=fill_size,
                fee=fee_per_contract * fill_size,
                liquidity="maker" if is_post_only else "taker",
                ts=book.ts_received,
                session_id=order.session_id,
            )
            fills.append(fill)
            order.filled_size += fill_size
            order.remaining_size = max(0, order.size - order.filled_size)
            order.average_fill_price = fill_price
            order.updated_at = book.ts_received
            order.status = "filled" if order.remaining_size == 0 else "partially_filled"
            state.submitted_book = book.model_copy(deep=True)
        return fills


def _would_cross_book(*, side: str, action: str, price: float, book: BinaryOrderBook) -> bool:
    tob = book.top_of_book()
    if action == "buy":
        cross_price = tob.yes_ask if side == "yes" else tob.no_ask
        return cross_price is not None and cross_price <= price
    cross_price = tob.yes_bid if side == "yes" else tob.no_bid
    return cross_price is not None and cross_price >= price


def _taker_cross(*, book: BinaryOrderBook, side: str, action: str) -> tuple[float, float] | None:
    """Return (price, size) of the top-of-book offer a taker would cross.

    Buys hit the ask; sells hit the bid. Returns None when no offer exists on
    the relevant side.
    """
    tob = book.top_of_book()
    if action == "buy":
        if side == "yes":
            if tob.yes_ask is None:
                return None
            return tob.yes_ask, tob.yes_ask_size
        if tob.no_ask is None:
            return None
        return tob.no_ask, tob.no_ask_size
    if side == "yes":
        if tob.yes_bid is None:
            return None
        return tob.yes_bid, tob.yes_bid_size
    if tob.no_bid is None:
        return None
    return tob.no_bid, tob.no_bid_size

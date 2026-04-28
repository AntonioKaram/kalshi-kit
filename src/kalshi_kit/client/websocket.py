from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import websockets

from kalshi_kit.client.rest import (
    KalshiRestClient,
)
from kalshi_kit.models.market import KalshiTicker
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.utils.time import utc_now

logger = logging.getLogger(__name__)


DEFAULT_WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
DEFAULT_DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"


@dataclass
class WsHealth:
    """Cross-client reconnect tracker.

    `last_reconnect_at` is set when the websocket comes back up after a drop.
    The first successful connect of a session is NOT a reconnect, so decisions
    in the opening window aren't spuriously flagged.
    """
    last_reconnect_at: datetime | None = None
    successful_connects: int = 0

    def mark_connect(self, *, ts: datetime | None = None) -> None:
        ts = ts or utc_now()
        self.successful_connects += 1
        if self.successful_connects > 1:
            self.last_reconnect_at = ts

    def is_reconnect_within(self, *, now: datetime, window_seconds: float) -> bool:
        if self.last_reconnect_at is None:
            return False
        return (now - self.last_reconnect_at).total_seconds() <= window_seconds


class MarketTickerSubscription:
    """Thread-safe holder for the current set of subscribed market tickers.

    Pass an instance to `KalshiWsClient.stream_market_data()` and call
    `replace()` from another task to change the subscription on the fly.
    The streaming loop notices the version bump and re-subscribes.
    """

    def __init__(self, market_tickers: list[str] | None = None) -> None:
        self._market_tickers = tuple(dict.fromkeys(market_tickers or []))
        self._version = 0
        self._lock = asyncio.Lock()

    async def replace(self, market_tickers: list[str]) -> bool:
        normalized = tuple(dict.fromkeys(market_tickers))
        async with self._lock:
            if normalized == self._market_tickers:
                return False
            self._market_tickers = normalized
            self._version += 1
            return True

    async def snapshot(self) -> tuple[list[str], int]:
        async with self._lock:
            return list(self._market_tickers), self._version


class KalshiWsClient:
    """WebSocket client for Kalshi market data with auto-reconnect.

    The Kalshi WebSocket API is read-only — all order operations go through
    `KalshiRestClient`. Authenticated channels (orderbook deltas, trades)
    require a signer; if no signer is available the client falls back to
    polling REST orderbooks.
    """

    def __init__(
        self,
        *,
        ws_url: str = DEFAULT_WS_URL,
        rest_client: KalshiRestClient,
        public_poll_seconds: float = 2.0,
        rest_orderbook_depth: int = 20,
    ) -> None:
        self.ws_url = ws_url
        self.rest_client = rest_client
        self.public_poll_seconds = public_poll_seconds
        self.rest_orderbook_depth = rest_orderbook_depth
        self.health = WsHealth()

    @classmethod
    def from_env(cls, *, demo: bool = False) -> KalshiWsClient:
        ws_url = os.getenv("KALSHI_WEBSOCKET_URL") or (DEFAULT_DEMO_WS_URL if demo else DEFAULT_WS_URL)
        rest = KalshiRestClient.from_env(demo=demo)
        return cls(ws_url=ws_url, rest_client=rest)

    async def __aenter__(self) -> KalshiWsClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def stream_market_data(
        self,
        market_tickers: list[str] | MarketTickerSubscription,
        *,
        include_ticker: bool = True,
        include_orderbook: bool = True,
        prefer_rest_orderbook: bool = False,
    ) -> AsyncIterator[tuple[str, Any]]:
        if include_orderbook and (prefer_rest_orderbook or not self.rest_client.has_trading_credentials):
            async for item in self._rest_poll_orderbooks(market_tickers):
                yield "orderbook", item
            return

        subscription_channels = []
        if include_ticker:
            subscription_channels.append("ticker")
        if include_orderbook:
            subscription_channels.append("orderbook_delta")

        headers = self._websocket_auth_headers()
        while True:
            current_tickers, subscription_version = await self._subscription_snapshot(market_tickers)
            if not current_tickers:
                await asyncio.sleep(self.public_poll_seconds)
                continue
            try:
                async with websockets.connect(
                    self.ws_url,
                    additional_headers=headers,
                    ping_interval=10,
                    ping_timeout=20,
                ) as ws:
                    self.health.mark_connect()
                    await ws.send(
                        json.dumps(
                            {
                                "id": 1,
                                "cmd": "subscribe",
                                "params": {
                                    "channels": subscription_channels,
                                    "market_tickers": current_tickers,
                                },
                            }
                        )
                    )
                    books: dict[str, BinaryOrderBook] = {}
                    while True:
                        next_tickers, next_version = await self._subscription_snapshot(market_tickers)
                        if next_version != subscription_version:
                            logger.info(
                                "kalshi market data subscription updated",
                                extra={
                                    "previous_tickers": current_tickers,
                                    "next_tickers": next_tickers,
                                },
                            )
                            break
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self.public_poll_seconds)
                        except TimeoutError:
                            continue
                        payload = json.loads(raw)
                        msg_type = payload.get("type")
                        if msg_type == "ticker":
                            yield "ticker", self._parse_ticker(payload)
                        elif msg_type == "orderbook_snapshot":
                            book = self._parse_orderbook_snapshot(payload)
                            books[book.market_ticker] = book
                            yield "orderbook", book
                        elif msg_type == "orderbook_delta":
                            book_ticker = payload["msg"]["market_ticker"]
                            existing = books.get(book_ticker)
                            if existing is None:
                                snapshot = await self.rest_client.get_orderbook(book_ticker)
                                book = self._parse_rest_orderbook(book_ticker, snapshot)
                                books[book.market_ticker] = book
                            else:
                                book = existing
                            book.apply_delta(
                                side=payload["msg"]["side"],
                                price=float(payload["msg"]["price_dollars"]),
                                delta=float(payload["msg"]["delta_fp"]),
                                ts_event=self._coerce_ts(payload["msg"].get("ts")) or utc_now(),
                                sequence=int(payload.get("seq", 0)),
                            )
                            yield "orderbook", book
                        elif msg_type == "error":
                            logger.error("kalshi websocket error: %s", payload)
            except Exception:
                logger.exception("kalshi websocket disconnected")
                await asyncio.sleep(2)

    def _websocket_auth_headers(self) -> dict[str, str] | None:
        signer = self.rest_client.signer
        if signer is None:
            return None
        return signer.sign("GET", self.ws_url)

    async def _rest_poll_orderbooks(
        self,
        market_tickers: list[str] | MarketTickerSubscription,
    ) -> AsyncIterator[BinaryOrderBook]:
        while True:
            current_tickers, version = await self._subscription_snapshot(market_tickers)
            if not current_tickers:
                await asyncio.sleep(self.public_poll_seconds)
                continue
            for ticker in current_tickers:
                payload = await self.rest_client.get_orderbook(ticker, depth=self.rest_orderbook_depth)
                yield self._parse_rest_orderbook(ticker, payload)
                _, next_version = await self._subscription_snapshot(market_tickers)
                if next_version != version:
                    break
            await asyncio.sleep(self.public_poll_seconds)

    def _parse_ticker(self, payload: dict[str, Any]) -> KalshiTicker:
        msg = payload["msg"]
        return KalshiTicker(
            market_ticker=msg["market_ticker"],
            ts_event=self._coerce_ts(msg.get("ts")) or utc_now(),
            yes_bid=float(msg["yes_bid_dollars"]) if msg.get("yes_bid_dollars") is not None else None,
            yes_ask=float(msg["yes_ask_dollars"]) if msg.get("yes_ask_dollars") is not None else None,
            no_bid=float(msg["no_bid_dollars"]) if msg.get("no_bid_dollars") is not None else None,
            no_ask=float(msg["no_ask_dollars"]) if msg.get("no_ask_dollars") is not None else None,
            last_price=float(msg["last_price_dollars"]) if msg.get("last_price_dollars") is not None else None,
            volume=float(msg["volume_dollars"]) if msg.get("volume_dollars") is not None else None,
            open_interest=float(msg["open_interest"]) if msg.get("open_interest") is not None else None,
            raw=msg,
        )

    def _parse_orderbook_snapshot(self, payload: dict[str, Any]) -> BinaryOrderBook:
        msg = payload["msg"]
        return BinaryOrderBook.from_levels(
            market_ticker=msg["market_ticker"],
            ts_event=utc_now(),
            ts_received=utc_now(),
            yes=[(float(price), float(size)) for price, size in msg.get("yes_dollars_fp", [])],
            no=[(float(price), float(size)) for price, size in msg.get("no_dollars_fp", [])],
            sequence=int(payload.get("seq", 0)),
        )

    def _parse_rest_orderbook(self, market_ticker: str, payload: dict[str, Any]) -> BinaryOrderBook:
        message = payload.get("orderbook_fp") or payload.get("orderbook") or {}
        return BinaryOrderBook.from_levels(
            market_ticker=market_ticker,
            ts_event=utc_now(),
            ts_received=utc_now(),
            yes=[(float(price), float(size)) for price, size in message.get("yes_dollars", message.get("yes", []))],
            no=[(float(price), float(size)) for price, size in message.get("no_dollars", message.get("no", []))],
        )

    @staticmethod
    def _coerce_ts(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            if value.endswith("Z"):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        if isinstance(value, (int, float)):
            if value > 10_000_000_000:
                return datetime.fromtimestamp(value / 1000, tz=UTC)
            return datetime.fromtimestamp(value, tz=UTC)
        return None

    async def _subscription_snapshot(
        self,
        market_tickers: list[str] | MarketTickerSubscription,
    ) -> tuple[list[str], int]:
        if isinstance(market_tickers, MarketTickerSubscription):
            return await market_tickers.snapshot()
        normalized = list(dict.fromkeys(market_tickers))
        return normalized, 0

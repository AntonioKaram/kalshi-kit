"""Quickstart: connect to Kalshi and stream a single market's order book.

Reads ``KALSHI_API_KEY_ID`` and ``KALSHI_PRIVATE_KEY_PATH`` from the environment.
Discovers an open KXBTC market via REST, then opens a WebSocket subscription
and prints the first orderbook snapshot's top of book before exiting.
"""

from __future__ import annotations

import asyncio

from kalshi_kit.client import KalshiRestClient, KalshiWsClient


async def main() -> None:
    rest = KalshiRestClient.from_env()
    markets = await rest.get_markets(event_ticker="KXBTC")
    ticker = markets[0].ticker

    async with KalshiWsClient.from_env() as ws:
        async for event_type, payload in ws.stream_market_data([ticker]):
            if event_type == "orderbook_snapshot":
                print(payload.top_of_book())
                break


if __name__ == "__main__":
    asyncio.run(main())

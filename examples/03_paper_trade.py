"""Paper-trade demo: live WS feed + PaperBroker + RandomEntryStrategy.

Reads ``KALSHI_API_KEY_ID`` and ``KALSHI_PRIVATE_KEY_PATH`` from the environment.
Streams orderbook snapshots for 60 seconds, dispatches them through the
strategy, lets the paper broker simulate fills, and prints a summary on exit.

Note: ``RandomEntryStrategy`` has zero economic edge by design. This script
exists to demonstrate plumbing, not to make money.
"""

from __future__ import annotations

import asyncio

from kalshi_kit.broker import PaperBroker
from kalshi_kit.client import KalshiRestClient, KalshiWsClient
from kalshi_kit.strategy.examples import RandomEntryStrategy


async def run(market_ticker: str, *, duration_seconds: float = 60.0) -> None:
    broker = PaperBroker()
    strategy = RandomEntryStrategy(broker, market_ticker, every_n_updates=10, seed=42)
    all_fills: list[object] = []

    async def stream() -> None:
        async with KalshiWsClient.from_env() as ws:
            async for event_type, payload in ws.stream_market_data([market_ticker]):
                if event_type != "orderbook_snapshot":
                    continue
                await strategy.on_book_update(payload)
                fills = broker.on_book_update(payload)
                for fill in fills:
                    await strategy.on_fill(fill)
                    all_fills.append(fill)

    try:
        await asyncio.wait_for(stream(), timeout=duration_seconds)
    except TimeoutError:
        pass

    print(f"orders submitted: {len(broker.orders)}")
    print(f"fills generated: {len(all_fills)}")
    for fill in all_fills:
        print(fill)


async def main() -> None:
    rest = KalshiRestClient.from_env()
    markets = await rest.get_markets(event_ticker="KXBTC", status="open")
    ticker = markets[0].ticker
    await run(ticker)


if __name__ == "__main__":
    asyncio.run(main())

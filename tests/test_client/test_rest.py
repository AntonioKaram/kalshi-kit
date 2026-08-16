from __future__ import annotations

from unittest.mock import AsyncMock, call

from kalshi_kit.client.rest import KalshiRestClient


async def test_get_multiple_orderbooks_repeats_keys_and_chunks_at_100() -> None:
    tickers = [f"TICKER-{index}" for index in range(201)]
    client = KalshiRestClient(signer=None)
    request = AsyncMock(
        side_effect=[
            {"orderbooks": [{"ticker": ticker} for ticker in tickers[:100]]},
            {"orderbooks": [{"ticker": ticker} for ticker in tickers[100:200]]},
            {"orderbooks": [{"ticker": tickers[200]}]},
        ]
    )
    client._request = request

    response = await client.get_multiple_orderbooks(tickers)

    assert response == {"orderbooks": [{"ticker": ticker} for ticker in tickers]}
    assert request.await_args_list == [
        call(
            "GET",
            "/markets/orderbooks",
            params=[("tickers", ticker) for ticker in tickers[:100]],
            authenticated=False,
        ),
        call(
            "GET",
            "/markets/orderbooks",
            params=[("tickers", ticker) for ticker in tickers[100:200]],
            authenticated=False,
        ),
        call(
            "GET",
            "/markets/orderbooks",
            params=[("tickers", tickers[200])],
            authenticated=False,
        ),
    ]

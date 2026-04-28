from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from kalshi_kit.client.auth import KalshiSigner

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_DEMO_BASE_URL = "https://demo-api.kalshi.co/trade-api/v2"


class KalshiRestClient:
    """Async REST client for the Kalshi exchange.

    Constructed either explicitly with a base URL and optional `KalshiSigner`,
    or via `KalshiRestClient.from_env()` which reads:

        KALSHI_API_KEY_ID         — required for authenticated endpoints
        KALSHI_PRIVATE_KEY_PATH   — required for authenticated endpoints
        KALSHI_BASE_URL           — defaults to production
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        signer: KalshiSigner | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self._signer = signer

    @classmethod
    def from_env(cls, *, demo: bool = False, timeout_seconds: float = 10.0) -> KalshiRestClient:
        base_url = os.getenv("KALSHI_BASE_URL") or (DEFAULT_DEMO_BASE_URL if demo else DEFAULT_BASE_URL)
        api_key_id = os.getenv("KALSHI_API_KEY_ID")
        private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        signer: KalshiSigner | None = None
        if api_key_id and private_key_path:
            signer = KalshiSigner.from_pem_file(api_key_id, Path(private_key_path))
        return cls(base_url=base_url, signer=signer, timeout_seconds=timeout_seconds)

    @property
    def has_trading_credentials(self) -> bool:
        return self._signer is not None

    @property
    def signer(self) -> KalshiSigner | None:
        return self._signer

    async def get_markets(self, **params: Any) -> dict[str, Any]:
        return await self._request("GET", "/markets", params=params, authenticated=False)

    async def get_market(self, ticker: str) -> dict[str, Any]:
        return await self._request("GET", f"/markets/{ticker}", authenticated=False)

    async def get_orderbook(self, ticker: str, depth: int | None = None) -> dict[str, Any]:
        params = {"depth": depth} if depth else None
        return await self._request("GET", f"/markets/{ticker}/orderbook", params=params, authenticated=False)

    async def get_multiple_orderbooks(self, tickers: list[str]) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/markets/orderbooks",
            params={"tickers": ",".join(tickers)},
            authenticated=False,
        )

    async def get_trades(self, **params: Any) -> dict[str, Any]:
        return await self._request("GET", "/markets/trades", params=params, authenticated=False)

    async def get_balance(self) -> dict[str, Any]:
        return await self._request("GET", "/portfolio/balance", authenticated=True)

    async def get_positions(self) -> dict[str, Any]:
        return await self._request("GET", "/portfolio/positions", authenticated=True)

    async def get_orders(self, **params: Any) -> dict[str, Any]:
        return await self._request("GET", "/portfolio/orders", params=params, authenticated=True)

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/portfolio/orders/{order_id}", authenticated=True)

    async def get_fills(self, **params: Any) -> dict[str, Any]:
        return await self._request("GET", "/portfolio/fills", params=params, authenticated=True)

    async def get_account_limits(self) -> dict[str, Any]:
        return await self._request("GET", "/account/limits", authenticated=True)

    async def get_user_data_timestamp(self) -> dict[str, Any]:
        return await self._request("GET", "/exchange/user_data_timestamp", authenticated=True)

    async def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/portfolio/orders", json_body=payload, authenticated=True)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/portfolio/orders/{order_id}", authenticated=True)

    async def amend_order(self, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/portfolio/orders/{order_id}/amend",
            json_body=payload,
            authenticated=True,
        )

    async def decrease_order(self, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/portfolio/orders/{order_id}/decrease",
            json_body=payload,
            authenticated=True,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        authenticated: bool,
    ) -> dict[str, Any]:
        if authenticated and self._signer is None:
            raise RuntimeError(
                "Kalshi authenticated request requires a KalshiSigner — set "
                "KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH and use KalshiRestClient.from_env()."
            )

        headers: dict[str, str] = {}
        if authenticated and self._signer is not None:
            headers.update(self._signer.sign(method, path))
            headers["Content-Type"] = "application/json"

        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, params=params, json=json_body, headers=headers)
            response.raise_for_status()
            return response.json()

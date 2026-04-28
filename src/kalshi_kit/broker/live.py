from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from kalshi_kit.broker.throttler import TokenBucketThrottler
from kalshi_kit.client._config import AppConfig
from kalshi_kit.client.auth import KalshiSigner
from kalshi_kit.client.rest import KalshiRestClient
from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.orders import OrderRecord, OrderRequest
from kalshi_kit.utils.time import ensure_utc, utc_now


class KalshiBroker:
    """Live broker that routes orders through `KalshiRestClient`.

    Construct either with an explicit `KalshiRestClient` (preferred — gives
    callers full control over auth and base URL) or with an `AppConfig`
    containing populated Kalshi credentials.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        client: KalshiRestClient | None = None,
    ) -> None:
        self.config = config or AppConfig()
        if client is None:
            signer: KalshiSigner | None = None
            if self.config.kalshi.api_key_id and self.config.kalshi.private_key_path:
                signer = KalshiSigner.from_pem_file(
                    self.config.kalshi.api_key_id,
                    Path(self.config.kalshi.private_key_path),
                )
            client = KalshiRestClient(
                base_url=self.config.kalshi.base_url,
                signer=signer,
                timeout_seconds=self.config.kalshi.request_timeout_seconds,
            )
        self.client = client
        self.read_throttler = TokenBucketThrottler(self.config.kalshi.read_rate_limit_per_second)
        self.write_throttler = TokenBucketThrottler(self.config.kalshi.write_rate_limit_per_second)

    async def submit_order(self, request: OrderRequest) -> OrderRecord:
        await self.write_throttler.acquire()
        cents = round(request.price * 100.0)
        payload = {
            "ticker": request.market_ticker,
            "action": request.action,
            "side": request.side,
            "count": request.size,
            "type": "limit",
            "client_order_id": request.client_order_id,
            "expiration_ts": (
                int(request.created_at.timestamp())
                + self.config.execution.order_expiration_buffer_seconds
            ),
        }
        if request.side == "yes":
            payload["yes_price"] = cents
        else:
            payload["no_price"] = cents
        response = await self.client.create_order(payload)
        order = response.get("order", response)
        return self._parse_order(
            order,
            fallback={
                "order_id": request.client_order_id,
                "client_order_id": request.client_order_id,
                "ticker": request.market_ticker,
                "side": request.side,
                "action": request.action,
                "count": request.size,
                "status": "new",
                "created_time": request.created_at,
                "updated_time": request.created_at,
                "trace_id": request.trace_id,
                "post_only": request.post_only,
                "reduce_only": request.reduce_only,
                f"{request.side}_price": cents,
            },
            session_id=request.session_id,
            trace_id=request.trace_id,
        )

    async def cancel_order(self, order_id: str) -> None:
        await self.write_throttler.acquire()
        await self.client.cancel_order(order_id)

    async def sync_orders(self) -> list[OrderRecord]:
        await self.read_throttler.acquire()
        payload = await self.client.get_orders(status="open")
        orders = _unwrap_collection(payload, preferred_keys=("orders", "open_orders"))
        return [self._parse_order(order, session_id="", trace_id="") for order in orders]

    async def sync_fills(self, *, min_ts: datetime | None = None) -> list[FillRecord]:
        await self.read_throttler.acquire()
        params: dict[str, Any] = {}
        if min_ts is not None:
            params["min_ts"] = int(ensure_utc(min_ts).timestamp() * 1000)
        payload = await self.client.get_fills(**params)
        fills = _unwrap_collection(payload, preferred_keys=("fills",))
        return [self._parse_fill(fill) for fill in fills]

    def _parse_order(
        self,
        payload: dict[str, Any],
        *,
        fallback: dict[str, Any] | None = None,
        session_id: str,
        trace_id: str,
    ) -> OrderRecord:
        data = {**(fallback or {}), **payload}
        created_at = _coerce_ts(
            data.get("created_time") or data.get("created_at") or data.get("created_ts") or data.get("time")
        ) or utc_now()
        updated_at = _coerce_ts(
            data.get("updated_time") or data.get("updated_at") or data.get("updated_ts") or data.get("time")
        ) or created_at
        return OrderRecord(
            order_id=str(data.get("order_id") or data.get("id") or data.get("client_order_id")),
            client_order_id=data.get("client_order_id"),
            market_ticker=data.get("ticker") or data.get("market_ticker"),
            side=str(data.get("side", "yes")).lower(),
            action=str(data.get("action", "buy")).lower(),
            status=str(data.get("status", "new")).lower(),
            price=_coerce_price(data, side=str(data.get("side", "yes")).lower()),
            size=int(_coerce_number(data.get("count") or data.get("size"), default=0)),
            filled_size=int(_coerce_number(data.get("filled_count") or data.get("filled_size"), default=0)),
            remaining_size=int(
                _coerce_number(
                    data.get("remaining_count")
                    or data.get("remaining_size")
                    or max(
                        _coerce_number(data.get("count") or data.get("size"), default=0)
                        - _coerce_number(data.get("filled_count") or data.get("filled_size"), default=0),
                        0,
                    ),
                    default=0,
                )
            ),
            average_fill_price=_coerce_optional_price(
                data,
                side=str(data.get("side", "yes")).lower(),
                keys=("average_fill_price_dollars", "average_fill_price", "avg_fill_price"),
            ),
            created_at=created_at,
            updated_at=updated_at,
            broker="kalshi",
            session_id=data.get("session_id", session_id),
            trace_id=data.get("trace_id", trace_id),
            metadata=data,
        )

    def _parse_fill(self, payload: dict[str, Any]) -> FillRecord:
        side = str(payload.get("side", "yes")).lower()
        ts = _coerce_ts(
            payload.get("created_time") or payload.get("created_at") or payload.get("time") or payload.get("ts")
        ) or utc_now()
        return FillRecord(
            fill_id=str(payload.get("fill_id") or payload.get("trade_id") or payload.get("id")),
            order_id=str(payload.get("order_id") or payload.get("maker_order_id") or payload.get("client_order_id")),
            client_order_id=payload.get("client_order_id"),
            market_ticker=payload.get("ticker") or payload.get("market_ticker"),
            side=side,
            action=str(payload.get("action", "buy")).lower(),
            price=_coerce_price(payload, side=side),
            size=int(_coerce_number(payload.get("count") or payload.get("size"), default=0)),
            fee=_coerce_number(payload.get("fee") or payload.get("fee_dollars"), default=0.0),
            liquidity=str(payload.get("liquidity") or ("taker" if payload.get("is_taker") else "maker")).lower(),
            ts=ts,
            session_id=str(payload.get("session_id", "")),
        )


def _unwrap_collection(payload: dict[str, Any], *, preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    for value in payload.values():
        if isinstance(value, list):
            return value
    return []


def _coerce_number(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_optional_price(payload: dict[str, Any], *, side: str, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if payload.get(key) is not None:
            price = _coerce_number(payload.get(key), default=0.0)
            return price / 100.0 if price > 1.0 and "dollars" not in key else price
    return None


def _coerce_price(payload: dict[str, Any], *, side: str) -> float:
    side_keys = (
        f"{side}_price_dollars",
        f"{side}_price",
        "price_dollars",
        "price",
    )
    for key in side_keys:
        if payload.get(key) is None:
            continue
        price = _coerce_number(payload.get(key), default=0.0)
        return price / 100.0 if price > 1.0 and "dollars" not in key else price
    return 0.0


def _coerce_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        try:
            return ensure_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=utc_now().tzinfo)
    return None

"""Internal config dataclasses used by extracted modules.

Public callers normally use the per-subsystem dataclasses directly
(`RiskConfig`, `ExecutionConfig`, etc.) and not the aggregate `AppConfig` —
the aggregate exists so the broker/risk modules carried over from the
private project compile without a large refactor.

Nothing here is imported in the user-facing API.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class KalshiConfig:
    base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    websocket_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    api_key_id: str | None = None
    private_key_path: str | None = None
    request_timeout_seconds: float = 10.0
    rest_orderbook_depth: int = 20
    public_poll_seconds: float = 2.0
    read_rate_limit_per_second: float = 5.0
    write_rate_limit_per_second: float = 5.0


@dataclass(slots=True)
class ExecutionConfig:
    paper_latency_ms: int = 150
    order_expiration_buffer_seconds: int = 60
    reject_if_stale: bool = True


@dataclass(slots=True)
class RiskConfig:
    daily_loss_limit: float = 100.0
    max_open_orders: int = 10
    max_gross_exposure_per_market: int = 100
    max_gross_exposure_total: int = 200
    max_expected_loss_per_trade: float = 50.0
    max_contracts_per_order: int = 10
    cooldown_after_losses: int = 3
    cooldown_minutes: int = 30
    max_stale_feed_breaches: int = 3


@dataclass(slots=True)
class SpotConfig:
    """Kept as a stub for forward-compat; spot connectors are not in v0.1."""

    stale_after_seconds: float = 5.0
    realized_vol_window_seconds: float = 60.0


@dataclass(slots=True)
class AppConfig:
    """Aggregate config consumed by broker, risk, and (future) replay modules.

    Defaults are reasonable for paper-trading; tune via constructor kwargs.
    """

    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    spot: SpotConfig = field(default_factory=SpotConfig)
    environment: str = "prod"
    session_id: str | None = None

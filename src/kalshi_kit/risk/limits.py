from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from kalshi_kit.client._config import AppConfig, RiskConfig
from kalshi_kit.utils.time import ensure_utc


@dataclass(slots=True)
class LimitDecision:
    allowed: bool
    reason: str


@dataclass
class RiskState:
    daily_realized_pnl: float = 0.0
    consecutive_losses: int = 0
    api_errors: int = 0
    stale_breaches: int = 0
    cooldown_until: datetime | None = None
    open_orders: int = 0
    per_market_exposure: dict[str, int] = field(default_factory=dict)
    total_exposure: int = 0


@dataclass(slots=True)
class TradeIntent:
    """Generic input to `RiskManager.can_trade`.

    Decoupled from any strategy-specific signal model: callers populate the
    fields the limit checks actually need.
    """

    market_ticker: str
    max_size: int
    target_price: float = 0.0
    reduce_only: bool = False


class RiskManager:
    """Pre-trade risk gate with daily-loss, exposure, and cooldown checks.

    Construct with either an `AppConfig` or a `RiskConfig` directly. The
    public API is `can_trade(intent, now=...)` returning a `LimitDecision`.
    """

    def __init__(self, config: AppConfig | RiskConfig) -> None:
        self.config = config if isinstance(config, AppConfig) else AppConfig(risk=config)
        self.state = RiskState()

    def can_trade(
        self,
        intent: TradeIntent,
        *,
        now: datetime,
        current_inventory: int | None = None,
        current_total_inventory: int | None = None,
        open_orders_count: int | None = None,
    ) -> LimitDecision:
        risk_cfg = self.config.risk
        if intent.reduce_only:
            if intent.max_size <= 0:
                return LimitDecision(False, "size_zero")
            return LimitDecision(True, "ok")
        if self.state.cooldown_until and ensure_utc(now) < ensure_utc(self.state.cooldown_until):
            return LimitDecision(False, "cooldown_active")
        if self.state.daily_realized_pnl <= -abs(risk_cfg.daily_loss_limit):
            return LimitDecision(False, "daily_loss_limit")
        open_count = open_orders_count if open_orders_count is not None else self.state.open_orders
        if open_count >= risk_cfg.max_open_orders:
            return LimitDecision(False, "max_open_orders")
        market_exposure = (
            current_inventory
            if current_inventory is not None
            else self.state.per_market_exposure.get(intent.market_ticker, 0)
        )
        if market_exposure + intent.max_size > risk_cfg.max_gross_exposure_per_market:
            return LimitDecision(False, "per_market_limit")
        total_exposure = (
            current_total_inventory if current_total_inventory is not None else self.state.total_exposure
        )
        if total_exposure + intent.max_size > risk_cfg.max_gross_exposure_total:
            return LimitDecision(False, "gross_exposure_limit")
        if intent.max_size <= 0:
            return LimitDecision(False, "size_zero")
        if (intent.target_price * intent.max_size) > risk_cfg.max_expected_loss_per_trade:
            return LimitDecision(False, "max_expected_loss")
        return LimitDecision(True, "ok")

    def on_order_submitted(self, market_ticker: str, size: int) -> None:
        self.state.open_orders += 1
        self.state.per_market_exposure[market_ticker] = (
            self.state.per_market_exposure.get(market_ticker, 0) + size
        )
        self.state.total_exposure += size

    def on_order_closed(self, market_ticker: str, remaining_size: int) -> None:
        self.state.open_orders = max(0, self.state.open_orders - 1)
        self.state.per_market_exposure[market_ticker] = max(
            0, self.state.per_market_exposure.get(market_ticker, 0) - remaining_size
        )
        self.state.total_exposure = max(0, self.state.total_exposure - remaining_size)

    def on_fill_pnl(self, realized_delta: float, *, now: datetime) -> None:
        self.state.daily_realized_pnl += realized_delta
        if realized_delta < 0:
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= self.config.risk.cooldown_after_losses:
                self.state.cooldown_until = ensure_utc(now) + timedelta(
                    minutes=self.config.risk.cooldown_minutes
                )
        else:
            self.state.consecutive_losses = 0

    def on_api_error(self) -> None:
        self.state.api_errors += 1

    def on_stale_data(self) -> None:
        self.state.stale_breaches += 1

    def on_fresh_data(self) -> None:
        self.state.stale_breaches = 0

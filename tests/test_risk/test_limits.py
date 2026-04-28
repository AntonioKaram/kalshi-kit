from datetime import UTC, datetime

from kalshi_kit.risk import RiskConfig, RiskManager, TradeIntent


def test_daily_loss_limit_blocks_trading() -> None:
    config = RiskConfig(daily_loss_limit=10.0)
    manager = RiskManager(config)
    manager.state.daily_realized_pnl = -config.daily_loss_limit
    intent = TradeIntent(market_ticker="BTC", max_size=1, target_price=0.45)
    decision = manager.can_trade(intent, now=datetime.now(tz=UTC))
    assert not decision.allowed
    assert decision.reason == "daily_loss_limit"


def test_cooldown_activates_after_losses() -> None:
    config = RiskConfig(cooldown_after_losses=3, cooldown_minutes=15)
    manager = RiskManager(config)
    now = datetime.now(tz=UTC)
    for _ in range(config.cooldown_after_losses):
        manager.on_fill_pnl(-1.0, now=now)
    assert manager.state.cooldown_until is not None
    assert manager.state.cooldown_until > now


def test_reduce_only_exit_allowed_under_daily_loss_limit() -> None:
    config = RiskConfig(daily_loss_limit=10.0)
    manager = RiskManager(config)
    manager.state.daily_realized_pnl = -config.daily_loss_limit
    intent = TradeIntent(
        market_ticker="BTC",
        max_size=2,
        target_price=0.55,
        reduce_only=True,
    )
    decision = manager.can_trade(intent, now=datetime.now(tz=UTC))
    assert decision.allowed is True


def test_per_market_exposure_blocks_when_overflowing() -> None:
    config = RiskConfig(max_gross_exposure_per_market=5)
    manager = RiskManager(config)
    intent = TradeIntent(market_ticker="BTC", max_size=6, target_price=0.50)
    decision = manager.can_trade(intent, now=datetime.now(tz=UTC))
    assert not decision.allowed
    assert decision.reason == "per_market_limit"

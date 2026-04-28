"""Risk management: pre-trade limits, kill switch, and PnL accounting."""

from __future__ import annotations

from kalshi_kit.client._config import RiskConfig
from kalshi_kit.risk.kill_switch import KillSwitch
from kalshi_kit.risk.limits import LimitDecision, RiskManager, RiskState, TradeIntent
from kalshi_kit.risk.pnl import apply_fill_to_position, mark_position, snapshot_portfolio

__all__ = [
    "KillSwitch",
    "LimitDecision",
    "RiskConfig",
    "RiskManager",
    "RiskState",
    "TradeIntent",
    "apply_fill_to_position",
    "mark_position",
    "snapshot_portfolio",
]

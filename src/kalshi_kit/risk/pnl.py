from __future__ import annotations

from datetime import datetime

from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.positions import PnLSnapshot, Position


def apply_fill_to_position(position: Position | None, fill: FillRecord) -> Position:
    base = position or Position(market_ticker=fill.market_ticker, updated_at=fill.ts)
    realized_delta = -fill.fee
    if fill.side == "yes":
        if fill.action == "buy":
            previous = base.yes_contracts
            new_total = previous + fill.size
            avg = ((base.average_yes_price or 0.0) * previous + fill.price * fill.size) / max(new_total, 1)
            base.yes_contracts = new_total
            base.average_yes_price = avg
        else:
            close_size = min(base.yes_contracts, fill.size)
            realized_delta += (fill.price - (base.average_yes_price or 0.0)) * close_size
            base.yes_contracts = max(base.yes_contracts - fill.size, 0)
            if base.yes_contracts == 0:
                base.average_yes_price = None
    else:
        if fill.action == "buy":
            previous = base.no_contracts
            new_total = previous + fill.size
            avg = ((base.average_no_price or 0.0) * previous + fill.price * fill.size) / max(new_total, 1)
            base.no_contracts = new_total
            base.average_no_price = avg
        else:
            close_size = min(base.no_contracts, fill.size)
            realized_delta += (fill.price - (base.average_no_price or 0.0)) * close_size
            base.no_contracts = max(base.no_contracts - fill.size, 0)
            if base.no_contracts == 0:
                base.average_no_price = None
    base.realized_pnl += realized_delta
    base.updated_at = fill.ts
    return base


def mark_position(position: Position, *, yes_mark: float | None, no_mark: float | None) -> Position:
    unrealized = 0.0
    if position.yes_contracts and position.average_yes_price is not None:
        unrealized += ((yes_mark or 0.0) - position.average_yes_price) * position.yes_contracts
    if position.no_contracts and position.average_no_price is not None:
        unrealized += ((no_mark or 0.0) - position.average_no_price) * position.no_contracts
    position.unrealized_pnl = unrealized
    return position


def snapshot_portfolio(
    *,
    positions: dict[str, Position],
    session_id: str,
    ts: datetime,
) -> PnLSnapshot:
    realized = sum(position.realized_pnl for position in positions.values())
    unrealized = sum(position.unrealized_pnl for position in positions.values())
    gross = sum(abs(position.yes_contracts) + abs(position.no_contracts) for position in positions.values())
    net = sum(position.yes_contracts - position.no_contracts for position in positions.values())
    return PnLSnapshot(
        ts=ts,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        gross_exposure=float(gross),
        net_exposure=float(net),
        session_id=session_id,
    )

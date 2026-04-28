"""Per-session diagnostic analysis for lag-repricing strategy evaluation.

Extracts metrics that the evidence gate doesn't capture: hold-time distribution,
signal→fill profitability, adverse-selection at fill, favorable-move realization
rate, and Phase 2 exit-reason counts (take-profit / invalidation / underwater).

Use via :func:`diagnose_session` for a single session or
:func:`aggregate_session_diagnostics` to fold results across sessions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any

import duckdb


@dataclass(slots=True)
class TradeLedgerEntry:
    market_ticker: str
    side: str
    entry_ts: Any
    exit_ts: Any | None
    entry_price: float
    exit_price: float | None
    size: int
    hold_seconds: float | None
    realized_pnl_per_contract: float | None


@dataclass(slots=True)
class DiagnosticBundle:
    session_path: str
    session_name: str
    # Fill counts
    total_fills: int = 0
    buy_fills: int = 0
    sell_fills: int = 0
    # Trade ledger
    closed_trades: int = 0
    hold_seconds: list[float] = field(default_factory=list)
    realized_pnl_per_contract: list[float] = field(default_factory=list)
    # Execution quality (per buy fill)
    adverse_deltas_cents: list[float] = field(default_factory=list)
    adversely_selected_count: int = 0
    # Signal validation (per buy fill)
    favorable_move_cents: list[float] = field(default_factory=list)
    favorable_within_window_count: int = 0
    # Exit reasons (from signals with reduce_only)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    # Entry rejections
    position_underwater_rejections: int = 0
    # Config used
    favorable_window_seconds: int = 120
    adverse_lookback_seconds: int = 5
    favorable_threshold_cents: float = 2.0


def diagnose_session(
    session_path: Path,
    *,
    favorable_window_seconds: int = 120,
    adverse_lookback_seconds: int = 5,
    favorable_threshold_cents: float = 2.0,
) -> DiagnosticBundle:
    db_path = session_path / "session.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    bundle = DiagnosticBundle(
        session_path=str(session_path),
        session_name=session_path.name,
        favorable_window_seconds=favorable_window_seconds,
        adverse_lookback_seconds=adverse_lookback_seconds,
        favorable_threshold_cents=favorable_threshold_cents,
    )
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        fills = _load_fills(connection)
        bundle.total_fills = len(fills)
        bundle.buy_fills = sum(1 for f in fills if f["action"] == "buy")
        bundle.sell_fills = sum(1 for f in fills if f["action"] == "sell")

        trades = _match_trade_ledger(fills)
        bundle.closed_trades = sum(1 for t in trades if t.exit_price is not None)
        bundle.hold_seconds = [t.hold_seconds for t in trades if t.hold_seconds is not None]
        bundle.realized_pnl_per_contract = [
            t.realized_pnl_per_contract for t in trades if t.realized_pnl_per_contract is not None
        ]

        # Adverse-selection and favorable-move: need per-fill orderbook lookups.
        for fill in fills:
            if fill["action"] != "buy":
                continue
            prior_bid = _best_bid_at_or_before(
                connection,
                market_ticker=fill["market_ticker"],
                side=fill["side"],
                reference_ts=fill["ts"],
                lookback_seconds=adverse_lookback_seconds,
            )
            if prior_bid is not None:
                delta_cents = (fill["price"] - prior_bid) * 100.0
                bundle.adverse_deltas_cents.append(delta_cents)
                if delta_cents < 0:
                    bundle.adversely_selected_count += 1

            future_max_bid = _max_bid_in_window(
                connection,
                market_ticker=fill["market_ticker"],
                side=fill["side"],
                start_ts=fill["ts"],
                window_seconds=favorable_window_seconds,
            )
            if future_max_bid is not None:
                fav_cents = (future_max_bid - fill["price"]) * 100.0
                bundle.favorable_move_cents.append(fav_cents)
                if fav_cents >= favorable_threshold_cents:
                    bundle.favorable_within_window_count += 1

        bundle.exit_reason_counts = _exit_reason_counts(connection)
        bundle.position_underwater_rejections = _count_rejection_reason(
            connection, reason="position_underwater"
        )
    finally:
        connection.close()
    return bundle


def aggregate_session_diagnostics(bundles: list[DiagnosticBundle]) -> dict[str, Any]:
    if not bundles:
        return {"session_count": 0}
    total_fills = sum(b.total_fills for b in bundles)
    buy_fills = sum(b.buy_fills for b in bundles)
    sell_fills = sum(b.sell_fills for b in bundles)
    closed_trades = sum(b.closed_trades for b in bundles)
    hold_seconds = [h for b in bundles for h in b.hold_seconds]
    realized_pnl_per_contract = [r for b in bundles for r in b.realized_pnl_per_contract]
    adverse_deltas = [d for b in bundles for d in b.adverse_deltas_cents]
    adversely_selected = sum(b.adversely_selected_count for b in bundles)
    favorable_moves = [f for b in bundles for f in b.favorable_move_cents]
    favorable_within_window = sum(b.favorable_within_window_count for b in bundles)
    exit_reasons: dict[str, int] = {}
    for b in bundles:
        for reason, count in b.exit_reason_counts.items():
            exit_reasons[reason] = exit_reasons.get(reason, 0) + count
    underwater = sum(b.position_underwater_rejections for b in bundles)
    hold_over_5min = sum(1 for h in hold_seconds if h > 300)
    trades_with_pnl = len(realized_pnl_per_contract)
    profitable_trades = sum(1 for r in realized_pnl_per_contract if r > 0)
    return {
        "session_count": len(bundles),
        "total_fills": total_fills,
        "buy_fills": buy_fills,
        "sell_fills": sell_fills,
        "closed_trades": closed_trades,
        "hold_seconds": {
            "median": median(hold_seconds) if hold_seconds else None,
            "mean": mean(hold_seconds) if hold_seconds else None,
            "count_over_5min": hold_over_5min,
            "total": len(hold_seconds),
        },
        "trade_pnl_cents": {
            "mean": mean(realized_pnl_per_contract) if realized_pnl_per_contract else None,
            "median": median(realized_pnl_per_contract) if realized_pnl_per_contract else None,
            "profitable_count": profitable_trades,
            "total": trades_with_pnl,
            "profitable_share": profitable_trades / trades_with_pnl if trades_with_pnl else None,
        },
        "adverse_selection": {
            "mean_delta_cents": mean(adverse_deltas) if adverse_deltas else None,
            "median_delta_cents": median(adverse_deltas) if adverse_deltas else None,
            "adversely_selected_count": adversely_selected,
            "total_buy_fills_analyzed": len(adverse_deltas),
            "adversely_selected_share": (
                adversely_selected / len(adverse_deltas) if adverse_deltas else None
            ),
        },
        "favorable_move": {
            "mean_cents": mean(favorable_moves) if favorable_moves else None,
            "median_cents": median(favorable_moves) if favorable_moves else None,
            "within_window_count": favorable_within_window,
            "total_buy_fills_analyzed": len(favorable_moves),
            "within_window_share": (
                favorable_within_window / len(favorable_moves) if favorable_moves else None
            ),
            "window_seconds": bundles[0].favorable_window_seconds,
            "threshold_cents": bundles[0].favorable_threshold_cents,
        },
        "exit_reason_counts": exit_reasons,
        "position_underwater_rejections": underwater,
    }


# ---------------------------------------------------------------------------
# Internal helpers

def _load_fills(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ts, market_ticker, side, action, price, size, order_id
        FROM fills
        ORDER BY ts, fill_id
        """
    ).fetchall()
    return [
        {
            "ts": row[0],
            "market_ticker": row[1],
            "side": row[2],
            "action": row[3],
            "price": float(row[4]),
            "size": int(row[5]),
            "order_id": row[6],
        }
        for row in rows
    ]


def _match_trade_ledger(fills: list[dict[str, Any]]) -> list[TradeLedgerEntry]:
    """FIFO-match buy fills to subsequent reduce_only sells per (market, side)."""
    open_positions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    entries: list[TradeLedgerEntry] = []
    for fill in fills:
        key = (fill["market_ticker"], fill["side"])
        if fill["action"] == "buy":
            open_positions.setdefault(key, []).append(
                {"ts": fill["ts"], "price": fill["price"], "size": fill["size"]}
            )
        elif fill["action"] == "sell":
            remaining = fill["size"]
            queue = open_positions.get(key, [])
            while remaining > 0 and queue:
                head = queue[0]
                matched = min(remaining, head["size"])
                hold_seconds = (fill["ts"] - head["ts"]).total_seconds()
                pnl_per_contract_cents = (fill["price"] - head["price"]) * 100.0
                entries.append(
                    TradeLedgerEntry(
                        market_ticker=fill["market_ticker"],
                        side=fill["side"],
                        entry_ts=head["ts"],
                        exit_ts=fill["ts"],
                        entry_price=head["price"],
                        exit_price=fill["price"],
                        size=matched,
                        hold_seconds=hold_seconds,
                        realized_pnl_per_contract=pnl_per_contract_cents,
                    )
                )
                head["size"] -= matched
                remaining -= matched
                if head["size"] == 0:
                    queue.pop(0)
    # Unclosed entries — report as hold-only so they surface in counts.
    for (market_ticker, side), queue in open_positions.items():
        for entry in queue:
            if entry["size"] > 0:
                entries.append(
                    TradeLedgerEntry(
                        market_ticker=market_ticker,
                        side=side,
                        entry_ts=entry["ts"],
                        exit_ts=None,
                        entry_price=entry["price"],
                        exit_price=None,
                        size=entry["size"],
                        hold_seconds=None,
                        realized_pnl_per_contract=None,
                    )
                )
    return entries


def _best_bid_at_or_before(
    connection: duckdb.DuckDBPyConnection,
    *,
    market_ticker: str,
    side: str,
    reference_ts: Any,
    lookback_seconds: int,
) -> float | None:
    """Best bid in effect ~lookback_seconds before reference_ts (most recent bid at-or-before that point)."""
    json_path = "$[0].price"
    column = "yes_bids" if side == "yes" else "no_bids"
    row = connection.execute(
        f"""
        SELECT CAST(json_extract({column}, '{json_path}') AS DOUBLE)
        FROM kalshi_orderbooks
        WHERE market_ticker = ?
          AND ts_event <= ? - INTERVAL {int(lookback_seconds)} SECOND
          AND {column} IS NOT NULL
        ORDER BY ts_event DESC
        LIMIT 1
        """,
        [market_ticker, reference_ts],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def _max_bid_in_window(
    connection: duckdb.DuckDBPyConnection,
    *,
    market_ticker: str,
    side: str,
    start_ts: Any,
    window_seconds: int,
) -> float | None:
    json_path = "$[0].price"
    column = "yes_bids" if side == "yes" else "no_bids"
    row = connection.execute(
        f"""
        SELECT MAX(CAST(json_extract({column}, '{json_path}') AS DOUBLE))
        FROM kalshi_orderbooks
        WHERE market_ticker = ?
          AND ts_event >= ?
          AND ts_event <= ? + INTERVAL {int(window_seconds)} SECOND
          AND {column} IS NOT NULL
        """,
        [market_ticker, start_ts, start_ts],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def _exit_reason_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    try:
        rows = connection.execute(
            """
            SELECT reason_code, COUNT(*)
            FROM signals
            WHERE reduce_only = TRUE
            GROUP BY reason_code
            """
        ).fetchall()
    except duckdb.Error:
        return {}
    return {str(row[0]): int(row[1]) for row in rows if row[0] is not None}


def _count_rejection_reason(connection: duckdb.DuckDBPyConnection, *, reason: str) -> int:
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM decision_events WHERE rejection_reason = ?",
            [reason],
        ).fetchone()
    except duckdb.Error:
        return 0
    return int(row[0]) if row and row[0] is not None else 0

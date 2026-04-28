from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from kalshi_kit.analysis.diagnostics import (
    aggregate_session_diagnostics,
    diagnose_session,
)


def _create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE fills (
            fill_id TEXT,
            ts TIMESTAMP,
            market_ticker TEXT,
            side TEXT,
            action TEXT,
            price DOUBLE,
            size INTEGER,
            order_id TEXT
        );
        CREATE TABLE kalshi_orderbooks (
            ts_event TIMESTAMP,
            market_ticker TEXT,
            yes_bids JSON,
            no_bids JSON
        );
        CREATE TABLE signals (
            reduce_only BOOLEAN,
            reason_code TEXT
        );
        CREATE TABLE decision_events (
            rejection_reason TEXT
        );
        """
    )


def _yes_bid(price: float) -> str:
    return f'[{{"price": {price}, "size": 100}}]'


def _build_session(tmp_path: Path) -> Path:
    session_path = tmp_path / "session"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)

    market = "KXBTC15M-60000"
    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)

    # Orderbook trajectory: bid rises then falls so we can observe adverse delta
    # relative to a point 20s before the buy fill, and favorable move within 120s.
    for offset, bid in [
        (0, 0.40),   # 20s prior to buy
        (15, 0.50),  # just before buy
        (20, 0.50),  # at buy ts
        (60, 0.55),  # favorable peak
        (120, 0.48),
    ]:
        conn.execute(
            "INSERT INTO kalshi_orderbooks VALUES (?, ?, ?, ?)",
            [t0 + timedelta(seconds=offset), market, _yes_bid(bid), None],
        )

    # Buy at t+20s at 0.50; sell at t+200s at 0.48 — 2c loss/contract, hold=180s.
    conn.execute(
        "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["f1", t0 + timedelta(seconds=20), market, "yes", "buy", 0.50, 2, "ord-1"],
    )
    conn.execute(
        "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["f2", t0 + timedelta(seconds=200), market, "yes", "sell", 0.48, 2, "ord-2"],
    )

    # Exit signal counts
    conn.execute(
        "INSERT INTO signals VALUES "
        "(TRUE, 'lag_cleanup_before_expiry'), "
        "(TRUE, 'lag_take_profit'), "
        "(FALSE, 'lag_entry')"
    )
    # One position_underwater rejection
    conn.execute(
        "INSERT INTO decision_events VALUES ('position_underwater'), ('edge_below_threshold')"
    )
    conn.close()
    return session_path


def test_diagnose_session_computes_expected_metrics(tmp_path: Path) -> None:
    session_path = _build_session(tmp_path)

    bundle = diagnose_session(
        session_path,
        favorable_window_seconds=120,
        adverse_lookback_seconds=20,
        favorable_threshold_cents=2.0,
    )

    assert bundle.total_fills == 2
    assert bundle.buy_fills == 1
    assert bundle.sell_fills == 1
    assert bundle.closed_trades == 1
    assert bundle.hold_seconds == [180.0]
    assert bundle.realized_pnl_per_contract == pytest.approx([-2.0])

    # Prior bid at T-20s was 0.40; buy at 0.50 → delta +10c (not adverse in this fixture).
    assert bundle.adverse_deltas_cents == pytest.approx([10.0])
    assert bundle.adversely_selected_count == 0

    # Max bid in [buy_ts, buy_ts+120s] is 0.55 → favorable 5c (above 2c threshold).
    assert bundle.favorable_move_cents == pytest.approx([5.0])
    assert bundle.favorable_within_window_count == 1

    assert bundle.exit_reason_counts == {
        "lag_cleanup_before_expiry": 1,
        "lag_take_profit": 1,
    }
    assert bundle.position_underwater_rejections == 1


def test_aggregate_session_diagnostics_folds_bundles(tmp_path: Path) -> None:
    session_path = _build_session(tmp_path)
    bundle = diagnose_session(
        session_path,
        favorable_window_seconds=120,
        adverse_lookback_seconds=20,
        favorable_threshold_cents=2.0,
    )

    aggregate = aggregate_session_diagnostics([bundle, bundle])

    assert aggregate["session_count"] == 2
    assert aggregate["total_fills"] == 4
    assert aggregate["buy_fills"] == 2
    assert aggregate["closed_trades"] == 2
    assert aggregate["hold_seconds"]["median"] == 180.0
    assert aggregate["hold_seconds"]["count_over_5min"] == 0
    assert aggregate["trade_pnl_cents"]["mean"] == pytest.approx(-2.0)
    assert aggregate["trade_pnl_cents"]["profitable_count"] == 0
    assert aggregate["trade_pnl_cents"]["profitable_share"] == 0.0
    assert aggregate["adverse_selection"]["adversely_selected_count"] == 0
    assert aggregate["adverse_selection"]["total_buy_fills_analyzed"] == 2
    assert aggregate["favorable_move"]["within_window_count"] == 2
    assert aggregate["favorable_move"]["within_window_share"] == 1.0
    assert aggregate["exit_reason_counts"] == {
        "lag_cleanup_before_expiry": 2,
        "lag_take_profit": 2,
    }
    assert aggregate["position_underwater_rejections"] == 2


def test_aggregate_handles_empty_list() -> None:
    assert aggregate_session_diagnostics([]) == {"session_count": 0}


def test_diagnose_flags_adversely_selected_buy(tmp_path: Path) -> None:
    session_path = tmp_path / "adverse"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)

    market = "KXBTC15M-60000"
    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    # Prior bid was 0.60; buy at 0.50 — 10c adverse.
    conn.execute(
        "INSERT INTO kalshi_orderbooks VALUES (?, ?, ?, ?)",
        [t0, market, _yes_bid(0.60), None],
    )
    conn.execute(
        "INSERT INTO kalshi_orderbooks VALUES (?, ?, ?, ?)",
        [t0 + timedelta(seconds=10), market, _yes_bid(0.50), None],
    )
    conn.execute(
        "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ["f1", t0 + timedelta(seconds=10), market, "yes", "buy", 0.50, 1, "ord-1"],
    )
    conn.close()

    bundle = diagnose_session(
        session_path,
        adverse_lookback_seconds=5,
        favorable_window_seconds=60,
    )
    assert bundle.adverse_deltas_cents == pytest.approx([-10.0])
    assert bundle.adversely_selected_count == 1

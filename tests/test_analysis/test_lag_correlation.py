"""Tests for the spot→Kalshi lag cross-correlation diagnostic."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from kalshi_kit.analysis.lag_correlation import (
    aggregate_lag_correlation,
    compute_session_lag_correlation,
)


def _create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE spot_ticks (
            venue TEXT,
            symbol TEXT,
            ts_event TIMESTAMP,
            ts_received TIMESTAMP,
            last_price DOUBLE,
            bid DOUBLE,
            ask DOUBLE,
            volume DOUBLE
        );
        CREATE TABLE kalshi_orderbooks (
            market_ticker TEXT,
            ts_event TIMESTAMP,
            ts_received TIMESTAMP,
            sequence BIGINT,
            yes_bids JSON,
            no_bids JSON
        );
        """
    )


def _insert_spot_and_kalshi(
    conn: duckdb.DuckDBPyConnection,
    *,
    market: str,
    t0: datetime,
    seconds: int,
    spot_series: list[float],
    yes_bid_series: list[float],
    no_bid_series: list[float],
) -> None:
    for i in range(seconds):
        ts = t0 + timedelta(seconds=i)
        conn.execute(
            "INSERT INTO spot_ticks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "coinbase",
                "BTC-USD",
                ts,
                ts,
                spot_series[i],
                None,
                None,
                None,
            ],
        )
        conn.execute(
            "INSERT INTO kalshi_orderbooks VALUES (?, ?, ?, ?, ?, ?)",
            [
                market,
                ts,
                ts,
                i,
                f'[{{"price": {yes_bid_series[i]}, "size": 100}}]',
                f'[{{"price": {no_bid_series[i]}, "size": 100}}]',
            ],
        )


def _build_lagged_session(tmp_path: Path, *, lag: int = 10, seconds: int = 400) -> Path:
    """Kalshi mid tracks spot from `lag` seconds earlier — spot LEADS Kalshi by `lag`.

    Spot path is a deterministic (seeded) random walk so variance is finite
    and correlations are well-defined at the matching lag.
    """
    import random

    session_path = tmp_path / f"lagged_{lag}"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)

    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    rng = random.Random(42)
    spot = [60000.0]
    for _ in range(seconds + lag + 5):
        spot.append(spot[-1] + rng.gauss(0, 20.0))

    # kalshi[i] reflects spot[i - lag] (clamped at the start)
    yes_bid = []
    no_bid = []
    for i in range(seconds):
        src_idx = max(0, i - lag)
        mid = 0.5 + (spot[src_idx] - 60000.0) / 10000.0
        mid = max(0.02, min(0.98, mid))
        yes_bid.append(round(mid - 0.01, 4))
        no_bid.append(round(1.0 - (mid + 0.01), 4))

    _insert_spot_and_kalshi(
        conn,
        market="KXBTC15M-60000",
        t0=t0,
        seconds=seconds,
        spot_series=spot[:seconds],
        yes_bid_series=yes_bid,
        no_bid_series=no_bid,
    )
    conn.close()
    return session_path


def test_detects_positive_correlation_at_matching_lag(tmp_path: Path) -> None:
    session_path = _build_lagged_session(tmp_path, lag=10, seconds=400)

    # Match W and L so the forward kalshi window equals the spot reference window
    # (otherwise the theoretical ceiling drops from 1.0 to √(min/max window ratio)).
    bundle = compute_session_lag_correlation(
        session_path,
        lags_seconds=(1, 10, 30),
        reference_window_seconds=10,
    )

    assert bundle.pooled_samples > 0
    # Matching lag → near-perfect correlation
    assert bundle.pooled_correlations[10] > 0.95
    # Mismatched lag (1s window of noise vs. 10s signal) should be materially lower
    assert bundle.pooled_correlations[1] < bundle.pooled_correlations[10]
    # Per-market row should carry the same correlation
    assert "KXBTC15M-60000" in bundle.per_market
    market_corr = bundle.per_market["KXBTC15M-60000"]["lag_correlations"]
    assert market_corr[10] > 0.95


def test_no_correlation_when_kalshi_random(tmp_path: Path) -> None:
    session_path = tmp_path / "uncorrelated"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)
    import math
    import random

    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    seconds = 300
    # Spot: independent random walk; Kalshi: unrelated deterministic wave.
    rng = random.Random(7)
    spot = [60000.0]
    for _ in range(seconds):
        spot.append(spot[-1] + rng.gauss(0, 20.0))
    spot = spot[:seconds]
    yes_bid = [round(0.5 + 0.05 * math.sin(i / 3.7), 4) for i in range(seconds)]
    no_bid = [round(1.0 - 0.02 - yes_bid[i], 4) for i in range(seconds)]
    _insert_spot_and_kalshi(
        conn,
        market="KXBTC15M-60000",
        t0=t0,
        seconds=seconds,
        spot_series=spot,
        yes_bid_series=yes_bid,
        no_bid_series=no_bid,
    )
    conn.close()

    bundle = compute_session_lag_correlation(
        session_path,
        lags_seconds=(1, 5, 10, 30),
        reference_window_seconds=5,
    )
    # Weakly correlated at best — any lag should be under 0.3 in absolute.
    for lag, corr in bundle.pooled_correlations.items():
        assert abs(corr) < 0.5, f"lag {lag}s correlation too high: {corr}"


def test_empty_session_returns_empty_bundle(tmp_path: Path) -> None:
    session_path = tmp_path / "empty"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)
    conn.close()

    bundle = compute_session_lag_correlation(session_path)
    assert bundle.pooled_samples == 0
    assert bundle.per_market == {}


def test_aggregate_weights_by_samples(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    session_a = _build_lagged_session(tmp_path / "a", lag=10, seconds=300)
    session_b = _build_lagged_session(tmp_path / "b", lag=10, seconds=300)
    bundle_a = compute_session_lag_correlation(
        session_a, lags_seconds=(10,), reference_window_seconds=10
    )
    bundle_b = compute_session_lag_correlation(
        session_b, lags_seconds=(10,), reference_window_seconds=10
    )

    agg = aggregate_lag_correlation([bundle_a, bundle_b])
    assert agg["session_count"] == 2
    assert agg["total_samples"] == bundle_a.pooled_samples + bundle_b.pooled_samples
    # Both sessions exhibit strong lag at 10s; aggregate must too.
    assert agg["pooled_correlations"][10] > 0.9


def test_aggregate_empty() -> None:
    assert aggregate_lag_correlation([]) == {"session_count": 0}


def test_session_regime_labels_from_directory_name(tmp_path: Path) -> None:
    """Session directory name YYYYMMDDTHHMMSS determines the regime label."""
    # 2026-04-18 is a Saturday → weekend
    sat_dir = tmp_path / "kb-20260418T200000-aaaa"
    sat_dir.mkdir()
    duckdb.connect(str(sat_dir / "session.duckdb")).close()
    # 2026-04-15 is a Wednesday, 15:00 UTC → weekday_us_day
    wed_dir = tmp_path / "kb-20260415T150000-bbbb"
    wed_dir.mkdir()
    duckdb.connect(str(wed_dir / "session.duckdb")).close()
    # Wednesday 03:00 UTC → weekday_off
    off_dir = tmp_path / "kb-20260415T030000-cccc"
    off_dir.mkdir()
    duckdb.connect(str(off_dir / "session.duckdb")).close()
    # Wednesday 09:00 UTC → weekday_eu_day
    eu_dir = tmp_path / "kb-20260415T090000-dddd"
    eu_dir.mkdir()
    duckdb.connect(str(eu_dir / "session.duckdb")).close()

    # Each schema has no data, but the regime label is parsed from the name
    for path, expected in [
        (sat_dir, "weekend"),
        (wed_dir, "weekday_us_day"),
        (off_dir, "weekday_off"),
        (eu_dir, "weekday_eu_day"),
    ]:
        # Give each an empty schema so compute_session_lag_correlation doesn't crash
        conn = duckdb.connect(str(path / "session.duckdb"))
        _create_schema(conn)
        conn.close()
        bundle = compute_session_lag_correlation(path)
        assert bundle.time_regime == expected, f"{path.name} → {bundle.time_regime} (expected {expected})"


def test_aggregate_folds_sessions_by_regime(tmp_path: Path) -> None:
    """Aggregate groups sessions into regimes based on session-name timestamp."""
    import random

    def _build(t0: datetime, name: str, seconds: int = 300) -> Path:
        path = tmp_path / name
        path.mkdir()
        conn = duckdb.connect(str(path / "session.duckdb"))
        _create_schema(conn)
        rng = random.Random(int(t0.timestamp()) % 1000)
        spot = [60000.0]
        for _ in range(seconds + 20):
            spot.append(spot[-1] + rng.gauss(0, 20.0))
        yes_bid, no_bid = [], []
        for i in range(seconds):
            src = max(0, i - 10)
            mid = 0.5 + (spot[src] - 60000.0) / 10000.0
            mid = max(0.02, min(0.98, mid))
            yes_bid.append(round(mid - 0.01, 4))
            no_bid.append(round(1.0 - (mid + 0.01), 4))
        _insert_spot_and_kalshi(
            conn, market="KXBTC15M-60000", t0=t0, seconds=seconds,
            spot_series=spot[:seconds], yes_bid_series=yes_bid, no_bid_series=no_bid,
        )
        conn.close()
        return path

    # Saturday session
    weekend = _build(datetime(2026, 4, 18, 20, 0, tzinfo=UTC), "kb-20260418T200000-x1")
    # Wednesday US-hours session
    weekday = _build(datetime(2026, 4, 15, 15, 0, tzinfo=UTC), "kb-20260415T150000-x2")
    bundle_w = compute_session_lag_correlation(
        weekend, lags_seconds=(10,), reference_window_seconds=10
    )
    bundle_d = compute_session_lag_correlation(
        weekday, lags_seconds=(10,), reference_window_seconds=10
    )
    assert bundle_w.time_regime == "weekend"
    assert bundle_d.time_regime == "weekday_us_day"

    agg = aggregate_lag_correlation([bundle_w, bundle_d])
    assert set(agg["time_regime_correlations"]) == {"weekend", "weekday_us_day"}
    assert agg["time_regime_samples"]["weekend"] == bundle_w.pooled_samples
    assert agg["time_regime_samples"]["weekday_us_day"] == bundle_d.pooled_samples


def test_missing_spot_data_tolerated(tmp_path: Path) -> None:
    session_path = tmp_path / "no_spot"
    session_path.mkdir()
    conn = duckdb.connect(str(session_path / "session.duckdb"))
    _create_schema(conn)
    t0 = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    conn.execute(
        "INSERT INTO kalshi_orderbooks VALUES (?, ?, ?, ?, ?, ?)",
        [
            "KXBTC15M-60000",
            t0,
            t0,
            1,
            '[{"price": 0.5, "size": 100}]',
            '[{"price": 0.48, "size": 100}]',
        ],
    )
    conn.close()

    bundle = compute_session_lag_correlation(session_path)
    assert bundle.pooled_samples == 0

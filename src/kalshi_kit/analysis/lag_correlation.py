"""Cross-correlation diagnostic: does spot lead Kalshi mid?

The lag-repricing thesis assumes spot price moves precede Kalshi market
moves on KXBTC15M. This module tests that hypothesis empirically by
correlating past spot returns (over a reference window) against forward
Kalshi-mid returns (at various lags).

A positive correlation at positive lag = spot leads Kalshi = thesis holds.
Zero or negative correlation = thesis is dead and Phase 6 (pivot) is on
the table.

Use :func:`compute_session_lag_correlation` for one session,
:func:`aggregate_lag_correlation` to fold across sessions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from kalshi_kit.utils.time import classify_time_regime


@dataclass(slots=True)
class LagCorrelationBundle:
    session_path: str
    session_name: str
    reference_window_seconds: int
    lags_seconds: tuple[int, ...]
    per_market: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Pooled across all markets in this session
    pooled_samples: int = 0
    pooled_correlations: dict[int, float] = field(default_factory=dict)
    # Volatility buckets (based on rolling abs spot return)
    vol_bucket_correlations: dict[str, dict[int, float]] = field(default_factory=dict)
    vol_bucket_samples: dict[str, int] = field(default_factory=dict)
    # Time regime for this session, derived from the UTC start time in the
    # session directory name. Per-row UTC is lossy in stored TIMESTAMPs
    # (DuckDB converts tz-aware to local-naive on write), so we label the
    # whole session with one regime. Sessions are ~1hr so this is fine.
    time_regime: str | None = None


def compute_session_lag_correlation(
    session_path: Path,
    *,
    lags_seconds: tuple[int, ...] = (1, 5, 10, 30, 60),
    reference_window_seconds: int = 5,
    sample_interval_seconds: float = 1.0,
    market_ticker: str | None = None,
) -> LagCorrelationBundle:
    """Correlate past spot returns against forward Kalshi-mid returns.

    For every sample instant t in each market:
      spot_return = spot[t] - spot[t - reference_window_seconds]
      kalshi_return[L] = kalshi_mid[t + L] - kalshi_mid[t]
    Pearson correlation is then computed over all valid sample instants.
    """
    db_path = session_path / "session.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    bundle = LagCorrelationBundle(
        session_path=str(session_path),
        session_name=session_path.name,
        reference_window_seconds=reference_window_seconds,
        lags_seconds=tuple(lags_seconds),
        time_regime=_session_time_regime(session_path.name),
    )

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        spot = _load_spot_series(connection, sample_interval_seconds)
        if spot.empty:
            return bundle
        kalshi_markets = _load_kalshi_mid_per_market(
            connection, sample_interval_seconds, market_ticker=market_ticker
        )
    finally:
        connection.close()

    pooled_frames: list[pd.DataFrame] = []
    for ticker, mid in kalshi_markets.items():
        if mid.empty:
            continue
        merged = _merge_spot_kalshi(spot, mid)
        if merged.empty:
            continue
        features = _build_feature_frame(
            merged,
            reference_window_seconds=reference_window_seconds,
            lags_seconds=lags_seconds,
        )
        if features.empty:
            bundle.per_market[ticker] = {"samples": 0, "lag_correlations": {}}
            continue
        per_market_corr = _pearson_lag_correlations(features, lags_seconds)
        bundle.per_market[ticker] = {
            "samples": len(features),
            "lag_correlations": per_market_corr,
        }
        pooled_frames.append(features)

    if pooled_frames:
        pooled = pd.concat(pooled_frames, ignore_index=True)
        bundle.pooled_samples = len(pooled)
        bundle.pooled_correlations = _pearson_lag_correlations(pooled, lags_seconds)
        bundle.vol_bucket_correlations, bundle.vol_bucket_samples = (
            _volatility_bucket_correlations(pooled, lags_seconds)
        )
    return bundle


def aggregate_lag_correlation(bundles: list[LagCorrelationBundle]) -> dict[str, Any]:
    """Fold per-session bundles. Reports sample-weighted correlations.

    Sample-weighting (rather than simple averaging) is deliberate: a 2-min
    session with 40 samples should not sway the aggregate the same as a
    55-min session with 3000 samples.
    """
    if not bundles:
        return {"session_count": 0}

    lags = bundles[0].lags_seconds
    ref_window = bundles[0].reference_window_seconds
    # We don't have the raw frames here, so re-aggregate by sample-weighting
    # the per-session correlations. For equal treatment, weight by session
    # samples; for exact pooling the caller should use raw frames.
    lag_sum: dict[int, float] = {lag: 0.0 for lag in lags}
    lag_weight: dict[int, float] = {lag: 0.0 for lag in lags}
    total_samples = 0
    vol_lag_sum: dict[str, dict[int, float]] = {}
    vol_lag_weight: dict[str, dict[int, float]] = {}
    vol_samples: dict[str, int] = {}
    regime_lag_sum: dict[str, dict[int, float]] = {}
    regime_lag_weight: dict[str, dict[int, float]] = {}
    regime_samples: dict[str, int] = {}

    for b in bundles:
        total_samples += b.pooled_samples
        for lag, corr in b.pooled_correlations.items():
            if pd.isna(corr):
                continue
            w = float(b.pooled_samples)
            lag_sum[lag] += corr * w
            lag_weight[lag] += w
        for bucket, corr_map in b.vol_bucket_correlations.items():
            w = float(b.vol_bucket_samples.get(bucket, 0))
            if w == 0:
                continue
            vol_samples[bucket] = vol_samples.get(bucket, 0) + int(w)
            vol_lag_sum.setdefault(bucket, {lag: 0.0 for lag in lags})
            vol_lag_weight.setdefault(bucket, {lag: 0.0 for lag in lags})
            for lag, corr in corr_map.items():
                if pd.isna(corr):
                    continue
                vol_lag_sum[bucket][lag] += corr * w
                vol_lag_weight[bucket][lag] += w
        regime = b.time_regime
        if regime is not None and b.pooled_samples > 0:
            w = float(b.pooled_samples)
            regime_samples[regime] = regime_samples.get(regime, 0) + int(w)
            regime_lag_sum.setdefault(regime, {lag: 0.0 for lag in lags})
            regime_lag_weight.setdefault(regime, {lag: 0.0 for lag in lags})
            for lag, corr in b.pooled_correlations.items():
                if pd.isna(corr):
                    continue
                regime_lag_sum[regime][lag] += corr * w
                regime_lag_weight[regime][lag] += w

    aggregate_corr = {
        lag: (lag_sum[lag] / lag_weight[lag]) if lag_weight[lag] > 0 else float("nan")
        for lag in lags
    }
    vol_bucket_aggregate = {
        bucket: {
            lag: (vol_lag_sum[bucket][lag] / vol_lag_weight[bucket][lag])
            if vol_lag_weight[bucket][lag] > 0
            else float("nan")
            for lag in lags
        }
        for bucket in vol_lag_sum
    }
    regime_aggregate = {
        regime: {
            lag: (regime_lag_sum[regime][lag] / regime_lag_weight[regime][lag])
            if regime_lag_weight[regime][lag] > 0
            else float("nan")
            for lag in lags
        }
        for regime in regime_lag_sum
    }
    return {
        "session_count": len(bundles),
        "total_samples": total_samples,
        "reference_window_seconds": ref_window,
        "lags_seconds": list(lags),
        "pooled_correlations": aggregate_corr,
        "vol_bucket_correlations": vol_bucket_aggregate,
        "vol_bucket_samples": vol_samples,
        "time_regime_correlations": regime_aggregate,
        "time_regime_samples": regime_samples,
    }


# ---------------------------------------------------------------------------
# Internal helpers

def _load_spot_series(
    connection: duckdb.DuckDBPyConnection, sample_interval_seconds: float
) -> pd.DataFrame:
    """Latest spot price per (sample_interval_seconds)-wide bucket."""
    try:
        df = connection.execute(
            """
            SELECT ts_event, last_price
            FROM spot_ticks
            WHERE last_price IS NOT NULL
            ORDER BY ts_event
            """
        ).fetchdf()
    except duckdb.Error:
        return pd.DataFrame(columns=["ts", "spot"])
    if df.empty:
        return pd.DataFrame(columns=["ts", "spot"])
    df["ts"] = pd.to_datetime(df["ts_event"])
    resampled = (
        df.set_index("ts")["last_price"]
        .resample(f"{sample_interval_seconds:g}s")
        .last()
        .ffill()
        .dropna()
    )
    return resampled.rename("spot").reset_index()


def _load_kalshi_mid_per_market(
    connection: duckdb.DuckDBPyConnection,
    sample_interval_seconds: float,
    *,
    market_ticker: str | None,
) -> dict[str, pd.DataFrame]:
    where = ""
    params: list[Any] = []
    if market_ticker is not None:
        where = "WHERE market_ticker = ?"
        params = [market_ticker]
    # Binary markets have yes_bids and no_bids only. yes_ask is implied as 1 - best_no_bid.
    try:
        df = connection.execute(
            f"""
            SELECT ts_event, market_ticker,
                   CAST(json_extract(yes_bids, '$[0].price') AS DOUBLE) AS yes_bid,
                   CAST(json_extract(no_bids, '$[0].price') AS DOUBLE) AS no_bid
            FROM kalshi_orderbooks
            {where}
            ORDER BY ts_event
            """,
            params,
        ).fetchdf()
    except duckdb.Error:
        return {}
    if df.empty:
        return {}
    df["yes_ask"] = 1.0 - df["no_bid"]
    df["mid"] = (df["yes_bid"] + df["yes_ask"]) / 2.0
    df = df.dropna(subset=["mid"])
    if df.empty:
        return {}
    df["ts"] = pd.to_datetime(df["ts_event"])
    out: dict[str, pd.DataFrame] = {}
    for ticker, group in df.groupby("market_ticker", sort=False):
        resampled = (
            group.set_index("ts")["mid"]
            .resample(f"{sample_interval_seconds:g}s")
            .last()
            .ffill()
            .dropna()
        )
        if resampled.empty:
            continue
        out[str(ticker)] = resampled.rename("kalshi_mid").reset_index()
    return out


def _merge_spot_kalshi(
    spot: pd.DataFrame, kalshi: pd.DataFrame
) -> pd.DataFrame:
    merged = pd.merge(spot, kalshi, on="ts", how="inner")
    return merged


def _build_feature_frame(
    merged: pd.DataFrame,
    *,
    reference_window_seconds: int,
    lags_seconds: tuple[int, ...],
) -> pd.DataFrame:
    """spot_ret = spot[t] - spot[t-W]; kalshi_ret_L = kalshi[t+L] - kalshi[t]."""
    if merged.empty:
        return merged
    frame = merged.copy()
    frame["spot_return"] = frame["spot"] - frame["spot"].shift(reference_window_seconds)
    for lag in lags_seconds:
        frame[f"kalshi_return_{lag}s"] = (
            frame["kalshi_mid"].shift(-lag) - frame["kalshi_mid"]
        )
    frame = frame.dropna()
    return frame


def _pearson_lag_correlations(
    frame: pd.DataFrame, lags_seconds: tuple[int, ...]
) -> dict[int, float]:
    out: dict[int, float] = {}
    if frame.empty or frame["spot_return"].std(ddof=0) == 0:
        return {lag: float("nan") for lag in lags_seconds}
    for lag in lags_seconds:
        col = f"kalshi_return_{lag}s"
        series = frame[col]
        if series.std(ddof=0) == 0:
            out[lag] = float("nan")
            continue
        out[lag] = float(frame["spot_return"].corr(series))
    return out


_SESSION_TS_RE = re.compile(r"(\d{8}T\d{6})")


def _session_time_regime(session_name: str) -> str | None:
    """Parse the UTC timestamp embedded in the session directory name.

    Format: ``kb-YYYYMMDDTHHMMSS-<hash>``. Returns the regime label from
    ``classify_time_regime`` or ``None`` if the name doesn't match.
    """
    match = _SESSION_TS_RE.search(session_name)
    if not match:
        return None
    try:
        ts = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    return classify_time_regime(ts)


def _volatility_bucket_correlations(
    frame: pd.DataFrame, lags_seconds: tuple[int, ...]
) -> tuple[dict[str, dict[int, float]], dict[str, int]]:
    """Bucket samples into low/mid/high tercile by |spot_return| and correlate per bucket."""
    if frame.empty:
        return {}, {}
    abs_ret = frame["spot_return"].abs()
    # qcut can fail on duplicate edges — fall back to a single bucket then.
    try:
        labels = pd.qcut(abs_ret, q=3, labels=["low_vol", "mid_vol", "high_vol"])
    except ValueError:
        return {}, {}
    bucket_corrs: dict[str, dict[int, float]] = {}
    bucket_samples: dict[str, int] = {}
    for bucket in ["low_vol", "mid_vol", "high_vol"]:
        mask = labels == bucket
        subset = frame[mask]
        if subset.empty:
            continue
        bucket_samples[bucket] = len(subset)
        bucket_corrs[bucket] = _pearson_lag_correlations(subset, lags_seconds)
    return bucket_corrs, bucket_samples

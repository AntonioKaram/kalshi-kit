from __future__ import annotations


def bucket_distance_to_strike(distance_bps: float | None) -> str:
    if distance_bps is None:
        return "unknown"
    absolute_distance = abs(float(distance_bps))
    if absolute_distance <= 50.0:
        return "0-50bps"
    if absolute_distance <= 150.0:
        return "50-150bps"
    if absolute_distance <= 300.0:
        return "150-300bps"
    return "300+bps"


def bucket_time_to_expiry(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 300.0:
        return "<5m"
    if seconds < 900.0:
        return "5-15m"
    if seconds < 1800.0:
        return "15-30m"
    return "30m+"

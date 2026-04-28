from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_unix_ms(value: datetime) -> int:
    return int(ensure_utc(value).timestamp() * 1000)


def age_seconds(ts: datetime, *, now: datetime | None = None) -> float:
    reference = ensure_utc(now or utc_now())
    return (reference - ensure_utc(ts)).total_seconds()


def seconds_to_timedelta(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


TIME_REGIMES = ("weekend", "weekday_us_day", "weekday_eu_day", "weekday_off")


def classify_time_regime(ts: datetime) -> str:
    """Bucket a UTC timestamp into one of the four time regimes.

    Mirrors the bucketing used by the lag-correlation diagnostic so strategy
    code and post-hoc analysis share the same definition.
    """
    utc_ts = ensure_utc(ts)
    weekday = utc_ts.weekday()  # Mon=0, Sun=6
    hour = utc_ts.hour
    if weekday >= 5:
        return "weekend"
    if 13 <= hour <= 20:
        return "weekday_us_day"
    if 7 <= hour <= 12:
        return "weekday_eu_day"
    return "weekday_off"

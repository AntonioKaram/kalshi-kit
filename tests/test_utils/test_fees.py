import math

import pytest

from kalshi_kit.utils.fees import (
    kalshi_round_trip_fee_dollars,
    kalshi_taker_fee_cents,
    kalshi_taker_fee_dollars,
)


@pytest.mark.parametrize(
    ("price", "expected_cents"),
    [
        (0.5, 2),   # ceil(7 * 0.25) = ceil(1.75) = 2
        (0.4, 2),   # ceil(7 * 0.24) = ceil(1.68) = 2
        (0.6, 2),   # symmetric to 0.4
        (0.1, 1),   # ceil(7 * 0.09) = ceil(0.63) = 1
        (0.9, 1),   # symmetric to 0.1
        (0.95, 1),  # ceil(7 * 0.0475) = ceil(0.3325) = 1
        (0.05, 1),  # symmetric to 0.95
        (0.01, 1),  # ceil(0.0693) = 1
        (0.0, 0),   # endpoint
        (1.0, 0),   # endpoint
    ],
)
def test_taker_fee_cents_matches_kalshi_formula(price: float, expected_cents: int) -> None:
    assert kalshi_taker_fee_cents(price) == expected_cents
    # Sanity: matches the raw formula directly.
    assert kalshi_taker_fee_cents(price) == math.ceil(7.0 * price * (1 - price))


def test_taker_fee_dollars_is_cents_divided_by_100() -> None:
    assert kalshi_taker_fee_dollars(0.5) == pytest.approx(0.02)
    assert kalshi_taker_fee_dollars(0.1) == pytest.approx(0.01)


def test_round_trip_fee_dollars_sums_two_legs() -> None:
    entry, exit_ = 0.5, 0.55
    expected = kalshi_taker_fee_dollars(entry) + kalshi_taker_fee_dollars(exit_)
    assert kalshi_round_trip_fee_dollars(entry, exit_) == pytest.approx(expected)

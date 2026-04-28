from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def cents_to_dollars(cents: float) -> float:
    return cents / 100.0


def dollars_to_cents(dollars: float) -> float:
    return dollars * 100.0


def round_price(price: float, tick_size: float = 0.01) -> float:
    scaled = Decimal(str(price / tick_size)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(scaled) * tick_size

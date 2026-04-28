"""Kalshi's official price-dependent per-fill fee.

Per the Kalshi fee schedule the fee for a single fill is
``ceil(7 * p * (1 - p))`` cents, charged on every fill (maker and taker
alike — Kalshi does not currently offer a maker rebate on KXBTC15M).

Single source of truth: paper broker, edge thresholds, and replay scripts
all import from here so paper, replay, and live calls share one fee model.
"""
from __future__ import annotations

import math


def kalshi_taker_fee_cents(price: float) -> float:
    return math.ceil(7.0 * price * (1.0 - price))


def kalshi_taker_fee_dollars(price: float) -> float:
    return kalshi_taker_fee_cents(price) / 100.0


def kalshi_round_trip_fee_dollars(entry_price: float, exit_price: float) -> float:
    return kalshi_taker_fee_dollars(entry_price) + kalshi_taker_fee_dollars(exit_price)

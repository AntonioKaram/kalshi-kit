# Kalshi fee calculator

Kalshi charges a per-fill taker fee that depends on the fill price. The
formula is:

```
fee_cents = ceil(7 * p * (1 - p))
```

where `p` is the fill price in dollars on the standard 0-1 scale (so a 50c
binary fill has `p = 0.50`). Fees are charged per fill, on both legs of a
round trip — there is no maker rebate on Kalshi, so passive fills incur
the same fee as taker fills.

The shape of the formula:

- It is symmetric around `p = 0.5`, where it peaks.
- The maximum per-fill fee is `ceil(7 * 0.25) = ceil(1.75) = 2` cents.
- It decays toward zero at the price extremes — fills near 0 or 1 are
  effectively free.

## Worked examples

The table below shows the per-fill and round-trip (entry + exit at the same
price, conservative case) fees at representative price levels:

| Fill price `p` | `7 * p * (1 - p)` | Per-fill fee | Round-trip fee |
|---:|---:|---:|---:|
| 0.05 | 0.3325 | 1c | 2c |
| 0.20 | 1.12   | 2c | 4c |
| 0.50 | 1.75   | 2c | 4c |
| 0.80 | 1.12   | 2c | 4c |
| 0.95 | 0.3325 | 1c | 2c |

Note that the ceiling rounds 1.75 up to 2 cents — the *theoretical* peak is
1.75c, but in practice every fill at any meaningfully central price pays
the full 2c.

## Computing in code

```python
from kalshi_kit.utils.fees import (
    kalshi_taker_fee_cents,
    kalshi_taker_fee_dollars,
    kalshi_round_trip_fee_dollars,
)

per_fill_cents = kalshi_taker_fee_cents(0.50)             # 2.0
per_fill_dollars = kalshi_taker_fee_dollars(0.50)         # 0.02
round_trip = kalshi_round_trip_fee_dollars(0.49, 0.51)    # entry + exit fees, in dollars
```

`kalshi_round_trip_fee_dollars` takes the entry and exit prices separately
because fees are charged on both legs at their respective prices, not on a
single mid.

## Strategy implication

Edges below roughly **3.5 cents** at `p = 0.5` are eaten by round-trip
fees alone, before slippage, adverse selection, or any other cost. On
near-strike KXBTC15M binaries, where 1-2c bid-ask is normal and observed
edges in the captured data ran at most a few cents, this is the dominant
constraint.

A useful sanity check before deploying any near-strike strategy: compute
the expected round-trip fee for the price range you will trade in,
multiply by your projected fill count per session, and compare against
your projected gross PnL. If gross PnL doesn't comfortably exceed fees by
a multiple, the strategy is unlikely to net positive in production.

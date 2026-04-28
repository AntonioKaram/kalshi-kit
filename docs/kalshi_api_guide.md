# Practical guide to the Kalshi API

This document collects practical gotchas observed while building and running
`kalshi-kit` against the live Kalshi venue. It is not a substitute for the
official API documentation, but it covers the points that cost the most
debugging time when they were learned the hard way.

## Auth

Kalshi uses **RSA-PSS request signing**, not JWT. There is no session token,
no refresh flow, and no login endpoint. Each individual request is signed
with the API key id and the private RSA key configured for that key id.

The signature is computed over `timestamp + method + path` (the path
including the leading slash, no query string, no body). The required
headers on every authenticated request:

```
KALSHI-ACCESS-KEY: <key_id>
KALSHI-ACCESS-SIGNATURE: <base64-rsa-pss-signature>
KALSHI-ACCESS-TIMESTAMP: <unix-ms-string>
Content-Type: application/json
```

Because there is no token, there is also no token expiry to manage and no
refresh logic to write. If a request fails with `401`, the cause is almost
always one of: clock skew on the signing host, a path mismatch (signed
path differs from the path actually sent), or a key-id / private-key pair
that does not match.

The `KalshiSigner` class in `kalshi_kit.client.auth` handles all of the
above; `KalshiRestClient.from_env()` reads `KALSHI_API_KEY_ID` and
`KALSHI_PRIVATE_KEY_PATH` and wires the signer onto the `httpx.AsyncClient`.

## Rate limits

Kalshi maintains **separate read and write token buckets** at the account
level. A naive client that uses one shared bucket will either burn budget on
order pollers and starve the order-submission path, or vice versa. The
`TokenBucketThrottler` in `kalshi_kit.broker` provides distinct buckets for
the two classes of request.

`429` responses **do not include a `Retry-After` header**. Clients must
implement their own backoff. The default behavior in `kalshi-kit` is
exponential with jitter, capped at a few seconds; the throttler also
preemptively waits when its local bucket is empty so that `429`s are rare
in steady state.

## Batch cancel

`POST /trade-api/v2/portfolio/orders/batch_cancel` costs **N tokens for N
orders**, not one token for the call. This matters when canceling a stack
in a hurry: a batch of 50 cancels can drain a 60-token write bucket.
Either pace cancels through the throttler or split them into smaller
groups.

## WebSocket

The WebSocket is **read-only**. It distributes order books, trades, and
account events. All order operations — create, modify, cancel — go
through REST (or FIX, if you have FIX access). Do not look for a
WebSocket order-submission endpoint; it does not exist.

`KalshiWsClient` reconnects automatically with exponential backoff and
restores the subscription state across reconnects. Consumers see a
continuous async iterator; reconnect events surface as `health_event`
yields rather than as exceptions.

## Order types

Kalshi supports limit and market orders, with IOC and GTC time-in-force,
plus `post_only` and `reduce_only` flags.

A non-obvious behavior: **non-marketable taker orders are rejected**, not
queued. If you submit an order that does not flag `post_only` and the
price does not cross the book, Kalshi returns a rejection rather than
resting the order. To rest passively, you must explicitly set
`post_only=True`. The `PaperBroker` enforces the same rule so that paper
results stay faithful.

## Settlement (KXBTC15M)

KXBTC15M binaries do **not** settle on the point-in-time Kalshi index value
at expiry. They settle on a 60-second TWAP of the **CFTC-published
RTI** (Real-Time Index) over the final minute of the contract.

Two implications:

1. The settlement print may diverge from any single-venue spot snapshot
   you might use as a fair-value reference.
2. Single-venue lead-lag signals decay against the TWAP — a five-second
   lead on Coinbase or Binance does not survive averaging over a full
   minute.

Strategies that assumed settlement = spot at expiry produced biased PnL
estimates in backtests; replays that respect the TWAP rule are honest.

## Common pitfalls

- **Cents vs dollars.** API order-submission prices are in **cents** (0–99
  for binary markets); fills, balances, and positions report dollars.
  `kalshi_kit` standardizes on dollars internally and converts at the
  REST boundary.
- **Ticker format.** Markets nest under events. KXBTC is an event series;
  individual markets look like `KXBTCD-26APR2715-T100000` — series, date,
  and strike concatenated. Filtering by `event_ticker` returns all
  markets in that series; filter further by status or strike yourself.
- **JWT expiry myth.** There is no JWT and therefore no expiry to handle.
  Stack Overflow answers and older blog posts that suggest "refresh your
  Kalshi JWT every 15 minutes" are wrong; ignore them.
- **`expiration_ts`.** This field is the **scheduled** market close time,
  not the time at which the market last became inactive. A market may
  resolve well before `expiration_ts` if the underlying triggers an early
  close, and `status` becomes `closed` independently of the timestamp.
  Use `status` for state checks and `expiration_ts` only for scheduling.

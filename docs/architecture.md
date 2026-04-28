# Architecture

## Overview

`kalshi-kit` is a research toolkit for building, paper-testing, and analyzing
trading strategies on Kalshi prediction markets. It is organized as a small
collection of single-purpose packages that communicate through Pydantic data
models. The runtime is asyncio-first: the REST client, WebSocket client, and
live broker are all `async`. Components are wired together by user code, not
by a framework — strategies own their event loop and decide which signals to
forward to brokers, risk, and storage.

The high-level data flow mirrors the diagram in the README:

```
Kalshi REST  ─┐
Kalshi WS    ─┴──▶ Strategy ──▶ Broker (paper / live) ──┐
                       ▲                                │
                       └── Risk + KillSwitch ◀──────────┤
                                                        │
                              storage.session (DuckDB) ◀┘
                                       │
                                       ├── analysis.diagnostics
                                       ├── analysis.lag_correlation
                                       └── parquet export
```

## Data flow

A typical live or paper run proceeds as follows:

1. The `KalshiWsClient` yields `(event_type, payload)` tuples — chiefly
   `orderbook_snapshot` carrying a `BinaryOrderBook`.
2. User code dispatches each event to its `Strategy`, which may inspect the
   book, consult `RiskManager` and `KillSwitch`, and submit `OrderRequest`
   objects to its `Broker`.
3. The broker (paper or live) returns `OrderRecord`s synchronously and emits
   `FillRecord`s as the book moves through resting orders. In live mode it
   talks to `KalshiRestClient`; in paper mode it simulates against the
   incoming book.
4. `DuckDBStore` persists order books, ticks, orders, fills, PnL snapshots,
   and health events as the session runs. Tables can be exported to Parquet
   via `store.export_parquet(path)`.
5. After the session, the `analysis` package replays the recorded data to
   produce diagnostics (hold time, adverse-selection rate, exit-reason mix)
   and lag-correlation reports across regime and volatility buckets.

## Module map

- `client/` — REST and WebSocket clients with RSA-PSS signing, throttling,
  and reconnect logic.
- `models/` — Pydantic v2 models shared across every other package: orders,
  fills, order books, market metadata, positions, ticks, health events.
- `broker/` — `Broker` protocol plus `PaperBroker` (in-memory simulation) and
  `KalshiBroker` (live REST execution), and the shared `TokenBucketThrottler`.
- `risk/` — `RiskManager` for pre-trade limits, `KillSwitch` for runtime
  halts, and PnL helpers (`apply_fill_to_position`, `mark_position`,
  `snapshot_portfolio`).
- `storage/` — `DuckDBStore` for live session capture and `ParquetSink` for
  cold-storage export. SQL schema lives in `storage/schema.sql`.
- `analysis/` — `diagnose_session` and `compute_session_lag_correlation`
  read recorded DuckDB sessions and emit microstructure summaries.
- `strategy/` — `Strategy` protocol, `BaseStrategy` no-op base class, and
  example strategies for reference.
- `utils/` — pure helpers: fees, UTC time handling, deterministic ids,
  math, bucketing, structured logging.

## Threading model

Everything is asyncio. There is a single event loop and no threading by
default. Specifically:

- REST calls are async (`httpx.AsyncClient`). The token-bucket throttler
  awaits when no tokens are available rather than blocking.
- WebSocket consumption is an async iterator. Reconnect logic is internal
  to `KalshiWsClient`; subscribers see a continuous stream.
- `PaperBroker.on_book_update` is **synchronous** because it performs no
  I/O — it inspects the in-memory order map and returns fills directly.
- `KalshiBroker` is async because every order op crosses the network.
- `DuckDBStore` is synchronous (DuckDB's Python driver is blocking); call
  it from inside the loop only when writes are infrequent, or move to a
  thread executor for high-rate captures.

## Extension points

`kalshi-kit` is designed to be extended without editing the package:

- **Custom strategies**: subclass `BaseStrategy` (or implement the
  `Strategy` protocol directly) and override the hooks you care about.
- **Custom brokers**: any object satisfying the `Broker` protocol from
  `kalshi_kit.broker.base` works in place of `PaperBroker` or
  `KalshiBroker` — useful for shadow execution, smart-order-router
  experiments, or testing harnesses.
- **Alternative storage**: `DuckDBStore` is a concrete class, but
  downstream code interacts with it through a small set of `insert_*`
  methods. Substituting a Postgres-backed or Arrow-backed sink is a
  straightforward refactor.
- **Custom analytics**: the analysis package reads DuckDB tables defined in
  `storage/schema.sql` and emits dataclasses; add new diagnostics by
  reading from those tables and following the existing `diagnose_session`
  shape.

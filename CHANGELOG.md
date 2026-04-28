# Changelog

All notable changes to `kalshi-kit` are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-04-27

Initial public release. GitHub-only — PyPI publishing deferred.

### Added

- **Kalshi REST client** with RSA-PSS request signing, separate read/write token-bucket rate limiting, and exponential backoff on `429` responses (Kalshi does not return `Retry-After`).
- **Kalshi WebSocket client** with auto-reconnect, exponential backoff, and subscription state preserved across reconnects. Streams orderbook snapshots/deltas, ticker, and trades.
- **Market discovery** utilities: enumerate markets by event-ticker prefix, filter by status / close time / strike distance.
- **Broker abstraction** (`broker.base.Broker` Protocol) with two implementations:
  - `broker.live.KalshiBroker` — routes orders to Kalshi REST.
  - `broker.paper.PaperBroker` — simulates fills from live orderbook updates with post-only crossing rules, queue-position estimates, latency simulation, and rejection of non-marketable taker orders.
- **DuckDB session storage** capturing orderbook snapshots, spot ticks, orders, fills, positions, PnL snapshots, and health events. Parquet export for archival.
- **Risk management**: `RiskManager` with daily loss limit, per-market and total gross exposure caps, max open orders, expected-loss-per-trade gate, and consecutive-loss cooldown. `KillSwitch` with auto-recovery from transient trips.
- **Diagnostics**: fill-level metrics (median hold time, adverse-selection rate, favorable-move realization, exit-reason mix) and lag-correlation analysis bucketed by time regime (US / EU / weekend) and volatility tercile.
- **`Strategy` Protocol** plus two example strategies: `RandomEntryStrategy` (uniform-random YES buys) and `SettlementTracker` (passive observer).
- **CLI** (`kalshi-kit`): `version`, `discover-markets`, `diagnose`, `diagnose-lag`.
- **Documentation**: architecture overview, Kalshi API gotchas guide, fee-formula walkthrough, microstructure notes from KXBTC15M observations.

### Notes

- Coinbase and Binance spot connectors that exist in the source project are intentionally **not included** in v0.1. They may be added in a future release.
- A generic **session replay engine** (the source project shipped a strategy-coupled one) is deferred to v0.2 — the `analysis.diagnostics` and `analysis.lag_correlation` modules ship today and operate on session DBs directly.
- The `record-session` and `report` CLI commands are deferred to v0.2 (they depend on the replay engine).
- Auth scheme is **RSA-PSS request signing**, not JWT. There is no session token to refresh.
- Fee formula implemented matches Kalshi's published model: `ceil(7 · p · (1 - p))` cents per fill.

# kalshi-kit

[![CI](https://github.com/AntonioKaram/kalshi-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/AntonioKaram/kalshi-kit/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**A Python toolkit for building, paper-testing, and analyzing trading strategies on Kalshi prediction markets.**

`kalshi-kit` is a batteries-included framework with REST + WebSocket connectivity, a paper broker that simulates fills from live order-book data, DuckDB session capture, and a microstructure analysis toolkit (lag correlation + fill-level diagnostics). It exists because building any of these from scratch — and getting them right — takes longer than building the strategy itself.

> **Status**: this is a research toolkit, not financial advice. The author built it while testing strategies on KXBTC15M; none produced durable edge. The infrastructure is what's published. See [What I learned](#what-i-learned).

---

## Why this exists

The public Kalshi Python ecosystem is thin. Existing options:

| Tool | Scope |
|---|---|
| [`ammario/kalshi`](https://github.com/ammario/kalshi) | Minimal REST wrapper |
| [`kalshi-rust`](https://github.com/dpeachpeach/kalshi-rust) | Rust-only |
| [`OctagonAI/kalshi-trading-bot-cli`](https://github.com/OctagonAI/kalshi-trading-bot-cli) | LLM-driven CLI for fundamentals research |

What was missing in Python: a **WebSocket client with reconnect**, **paper broker with realistic fill simulation**, **replay framework**, and **microstructure analysis** in one package, sharing data models. That's what this is.

---

## Install

```bash
pip install git+https://github.com/AntonioKaram/kalshi-kit.git
```

Requires Python 3.12+. PyPI publishing is planned but not active for v0.1.

---

## Quickstart

Read a live order book in under ten lines:

```python
import asyncio
from kalshi_kit import KalshiRestClient, KalshiWsClient

async def main():
    rest = KalshiRestClient.from_env()                    # KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH
    response = await rest.get_markets(event_ticker="KXBTC", status="open")
    ticker = response["markets"][0]["ticker"]

    async with KalshiWsClient.from_env() as ws:
        async for event_type, book in ws.stream_market_data([ticker]):
            if event_type == "orderbook":
                print(book.top_of_book())
                break

asyncio.run(main())
```

Set credentials via environment:

```bash
export KALSHI_API_KEY_ID="..."
export KALSHI_PRIVATE_KEY_PATH="/path/to/key.pem"
```

---

## Features

### REST + WebSocket with auth, rate limiting, and reconnect

```python
from kalshi_kit.client import KalshiRestClient

rest = KalshiRestClient.from_env()
balance = await rest.get_balance()
order = await rest.create_order(
    market_ticker="KXBTCD-26APR2715-T100000",
    side="yes", action="buy",
    type="limit", price=42, count=10,
    post_only=True,
)
```

- **RSA-PSS signing** (Kalshi's auth scheme) — every request signed with timestamp + method + path. No tokens, no refresh.
- **Token-bucket throttler** with separate read/write buckets. Backs off on `429` (Kalshi doesn't return `Retry-After`).
- **WebSocket** auto-reconnect with exponential backoff; subscription state preserved across reconnects.

### Market discovery

```python
from kalshi_kit.client import discover_markets

markets = await discover_markets(rest, event_ticker_prefix="KXBTC", status="open")
near_strike = [m for m in markets if abs(m.strike_distance_bps()) < 100]
```

### Paper broker

The same `Broker` interface backs live and paper. Switch modes by swapping one import:

```python
from kalshi_kit import KalshiWsClient, PaperBroker

broker = PaperBroker(paper_latency_ms=50)
async with KalshiWsClient.from_env() as ws:
    async for event_type, book in ws.stream_market_data([ticker]):
        if event_type == "orderbook":
            fills = broker.on_book_update(book)   # generates fills if resting orders cross
```

Paper fills respect: post-only crossing rules, queue-position estimates, latency, and Kalshi's behavior of rejecting non-marketable taker orders.

### Session capture

```python
from kalshi_kit.storage import DuckDBStore

store = DuckDBStore.open("sessions/2026-04-27.duckdb")
store.insert_orderbook(book)         # called from your runtime as events arrive
store.insert_fill(fill)
store.export_parquet("archives/")    # archive snapshot for offline analysis
```

DuckDB tables: `kalshi_orderbooks`, `spot_ticks`, `orders`, `fills`, `positions`, `pnl_snapshots`, `health_events`. A generic session-replay engine is planned for v0.2.

### Microstructure analysis

```bash
kalshi-kit diagnose --session sessions/2026-04-27.duckdb
# → median hold time, adverse-selection rate, favorable-move realization, exit-reason mix

kalshi-kit diagnose-lag --session sessions/2026-04-27.duckdb
# → spot-Kalshi cross-correlation by lag, time regime (US/EU/weekend), volatility tercile
```

### Risk management

```python
from kalshi_kit.risk import RiskManager, KillSwitch, RiskConfig

risk = RiskManager(RiskConfig(
    daily_loss_limit_dollars=50.0,
    max_gross_exposure_per_market_dollars=100.0,
    max_open_orders=10,
))
kill = KillSwitch()
if not risk.can_trade(order_request, position_state) or kill.active:
    return
```

Trips on stale data, repeated API errors, or daily-loss breach. Auto-recovers from transient trips after a configurable cooldown.

---

## Architecture

```
                 ┌────────────────────────────┐
   Kalshi REST ──┤ client.rest                ├──┐
   Kalshi WS  ───┤ client.websocket           │  │
                 └────────────────────────────┘  │
                                                 ▼
                                         ┌──────────────┐       ┌──────────────┐
                                         │  Strategy    │──────▶│  Broker      │──┐
                                         │  (your code) │       │  paper/live  │  │
                                         └──────────────┘       └──────────────┘  │
                                                ▲                                  │
                                                │                                  │
                                                │            ┌──────────────┐      │
                                                └────────────│ Risk + Kill  │◀─────┤
                                                             └──────────────┘      │
                                                ┌────────────────────────────┐     │
                                                │  storage.session (DuckDB)  │◀────┘
                                                └────────────────────────────┘
                                                          ▲          │
                                                          │          ▼
                                                          │   analysis.replay
                                                          │   analysis.diagnostics
                                                          │   analysis.lag_correlation
                                                          └─── parquet export
```

Read in detail: [`docs/architecture.md`](docs/architecture.md).

---

## What I learned

I built `kalshi-kit` while testing strategies on KXBTC15M (15-minute Bitcoin binaries). Five strategy variants and ~2 weeks of evidence later, none produced durable edge. The infrastructure was the durable output. A few practical findings worth knowing if you're building on Kalshi:

- **Auth is RSA-PSS, not JWT.** Sign each request with `timestamp + method + path`. No session tokens, no refresh logic to maintain.
- **`429` responses don't include `Retry-After`.** You must implement your own exponential backoff. A single token bucket across reads and writes is wrong — Kalshi rate-limits them separately.
- **Batch cancel costs N tokens, not 1.** Plan accordingly when canceling a stack.
- **The WebSocket is read-only.** All order operations go through REST (or FIX, if you have access).
- **Fees: `⌈7 · p · (1 − p)⌉` cents per fill.** Peak 2¢ per leg at `p = 0.5` (since `7 · 0.25 = 1.75` rounds up), dropping toward zero at the extremes. A round-trip near 50¢ costs 4¢ — meaningful relative to the 1–2¢ edges available on near-strike binaries.
- **KXBTC15M settles on a 60-second TWAP** of CFTC-published RTI, not a point-in-time print. Single-venue lead-lag signals decay against this.
- **Adverse selection on passive entries: ~94%** in the data this toolkit captured. Maker rebates do not exist on Kalshi; passive fills carry no compensating premium.

A longer write-up is in progress; link will appear here when published.

---

## Examples

The [`examples/`](examples/) directory has six runnable scripts:

1. `01_quickstart.py` — connect and stream a single market.
2. `02_market_discovery.py` — enumerate KXBTC markets, filter by status and strike distance.
3. `03_paper_trade.py` — `PaperBroker` + `RandomEntryStrategy` on the live WS feed.
4. `05_analyze_session.py` — post-hoc diagnostics on a recorded session.

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — system architecture and data flow
- [`docs/kalshi_api_guide.md`](docs/kalshi_api_guide.md) — practical guide to Kalshi API behavior
- [`docs/fee_calculator.md`](docs/fee_calculator.md) — fee formula derivation and worked examples
- [`docs/microstructure_notes.md`](docs/microstructure_notes.md) — observations on KXBTC15M microstructure

---

## Contributing

Issues and PRs welcome. Run the test suite:

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy src/
```

See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md).

---

## License

MIT. Not affiliated with KalshiEX LLC.

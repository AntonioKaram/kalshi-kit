"""DuckDB-backed session store.

Persists everything captured during a paper or live trading session:
market metadata, spot ticks, Kalshi orderbooks/tickers, orders, fills,
positions, PnL snapshots, and health events. Replay and analysis modules
read back from these tables.

The schema lives in `schema.sql` and is applied on `open()`. Tables are
created with `CREATE IF NOT EXISTS`, so reopening an existing DB is safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from kalshi_kit.models.fills import FillRecord
from kalshi_kit.models.market import HealthEvent, KalshiTicker, MarketMetadata, SpotTick
from kalshi_kit.models.orderbook import BinaryOrderBook
from kalshi_kit.models.orders import OrderRecord, OrderStateTransition
from kalshi_kit.models.positions import PnLSnapshot, Position
from kalshi_kit.utils.time import utc_now

DEFAULT_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class DuckDBStore:
    def __init__(self, db_path: Path | str, schema_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
        self.connection = duckdb.connect(str(self.db_path))
        self.connection.execute(schema.read_text(encoding="utf-8"))

    @classmethod
    def open(cls, db_path: Path | str) -> DuckDBStore:
        return cls(db_path)

    def close(self) -> None:
        self.connection.close()

    def insert_market_metadata(self, market: MarketMetadata) -> None:
        payload = market.model_dump()
        payload["raw"] = json.dumps(payload["raw"], default=str)
        payload["recorded_at"] = utc_now()
        self._insert("market_metadata", payload)

    def insert_spot_tick(self, tick: SpotTick) -> None:
        self._insert("spot_ticks", tick.model_dump())

    def insert_orderbook(self, book: BinaryOrderBook) -> None:
        payload = book.model_dump()
        payload["yes_bids"] = json.dumps(payload["yes_bids"], default=str)
        payload["no_bids"] = json.dumps(payload["no_bids"], default=str)
        self._insert("kalshi_orderbooks", payload)

    def insert_kalshi_ticker(self, ticker: KalshiTicker) -> None:
        payload = ticker.model_dump()
        payload["raw"] = json.dumps(payload["raw"], default=str)
        self._insert("kalshi_tickers", payload)

    def insert_order(self, order: OrderRecord) -> None:
        payload = order.model_dump()
        payload["metadata"] = json.dumps(payload["metadata"], default=str)
        self._insert("orders", payload)

    def insert_order_transition(self, transition: OrderStateTransition) -> None:
        self._insert("order_state_transitions", transition.model_dump())

    def insert_fill(self, fill: FillRecord) -> None:
        self._insert("fills", fill.model_dump())

    def upsert_position(self, position: Position) -> None:
        self.connection.execute(
            "DELETE FROM positions WHERE market_ticker = ?", [position.market_ticker]
        )
        self._insert("positions", position.model_dump())

    def insert_pnl(self, pnl: PnLSnapshot) -> None:
        self._insert("pnl_snapshots", pnl.model_dump())

    def insert_health_event(self, event: HealthEvent) -> None:
        self._insert("health_events", event.model_dump())

    def insert_kill_switch_event(
        self, *, ts: Any, state: str, reason: str, session_id: str
    ) -> None:
        self._insert(
            "kill_switch_events",
            {"ts": ts, "state": state, "reason": reason, "session_id": session_id},
        )

    def export_parquet(self, output_dir: Path | str) -> None:
        """Dump every populated table to a Parquet file under `output_dir`."""

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        tables = [
            "market_metadata",
            "spot_ticks",
            "kalshi_orderbooks",
            "kalshi_tickers",
            "orders",
            "order_state_transitions",
            "fills",
            "positions",
            "pnl_snapshots",
            "health_events",
            "kill_switch_events",
        ]
        for table in tables:
            count = self._scalar(f"SELECT count(*) FROM {table}") or 0
            if count == 0:
                continue
            self.connection.execute(
                f"COPY (SELECT * FROM {table}) TO '{out / f'{table}.parquet'}' (FORMAT PARQUET)"
            )

    def latest_status(self) -> dict[str, Any]:
        return {
            "spot_age_seconds": self._scalar(
                "SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - max(ts_received))) FROM spot_ticks"
            ),
            "kalshi_age_seconds": self._scalar(
                "SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - max(ts_received))) FROM kalshi_orderbooks"
            ),
            "open_orders": self._scalar(
                "SELECT count(*) FROM orders WHERE status IN ('new', 'resting', 'partially_filled')"
            )
            or 0,
            "realized_pnl": self._scalar(
                "SELECT realized_pnl FROM pnl_snapshots ORDER BY ts DESC LIMIT 1"
            )
            or 0.0,
            "unrealized_pnl": self._scalar(
                "SELECT unrealized_pnl FROM pnl_snapshots ORDER BY ts DESC LIMIT 1"
            )
            or 0.0,
        }

    def latest_positions(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT market_ticker, yes_contracts, no_contracts, realized_pnl, unrealized_pnl, updated_at
            FROM positions
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [
            {
                "market_ticker": row[0],
                "yes_contracts": row[1],
                "no_contracts": row[2],
                "realized_pnl": row[3],
                "unrealized_pnl": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def latest_kill_switch(self) -> dict[str, Any]:
        row = self.connection.execute(
            """
            SELECT state, reason, ts, session_id
            FROM kill_switch_events
            ORDER BY ts DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return {"active": False, "reason": None, "ts": None}
        return {
            "active": row[0] == "tripped",
            "reason": row[1],
            "ts": row[2],
            "session_id": row[3],
        }

    def _scalar(self, query: str) -> Any:
        row = self.connection.execute(query).fetchone()
        return row[0] if row else None

    def _insert(self, table: str, payload: dict[str, Any]) -> None:
        keys = list(payload.keys())
        placeholders = ", ".join(["?"] * len(keys))
        columns = ", ".join(keys)
        values = [payload[key] for key in keys]
        self.connection.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", values
        )

CREATE TABLE IF NOT EXISTS market_metadata (
  ticker TEXT,
  event_ticker TEXT,
  title TEXT,
  subtitle TEXT,
  status TEXT,
  yes_sub_title TEXT,
  no_sub_title TEXT,
  open_time TIMESTAMP,
  close_time TIMESTAMP,
  expiration_time TIMESTAMP,
  latest_expiration_time TIMESTAMP,
  expected_expiration_time TIMESTAMP,
  settlement_ts TIMESTAMP,
  strike_type TEXT,
  floor_strike DOUBLE,
  cap_strike DOUBLE,
  functional_strike TEXT,
  rules_primary TEXT,
  rules_secondary TEXT,
  can_close_early BOOLEAN,
  tick_size INTEGER,
  market_type TEXT,
  response_price_units TEXT,
  liquidity_dollars DOUBLE,
  raw JSON,
  recorded_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spot_ticks (
  venue TEXT,
  symbol TEXT,
  ts_event TIMESTAMP,
  ts_received TIMESTAMP,
  last_price DOUBLE,
  bid DOUBLE,
  ask DOUBLE,
  volume DOUBLE
);

CREATE TABLE IF NOT EXISTS kalshi_orderbooks (
  market_ticker TEXT,
  ts_event TIMESTAMP,
  ts_received TIMESTAMP,
  sequence BIGINT,
  yes_bids JSON,
  no_bids JSON
);

CREATE TABLE IF NOT EXISTS kalshi_tickers (
  market_ticker TEXT,
  ts_event TIMESTAMP,
  yes_bid DOUBLE,
  yes_ask DOUBLE,
  no_bid DOUBLE,
  no_ask DOUBLE,
  last_price DOUBLE,
  volume DOUBLE,
  open_interest DOUBLE,
  raw JSON
);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT,
  client_order_id TEXT,
  market_ticker TEXT,
  side TEXT,
  action TEXT,
  status TEXT,
  price DOUBLE,
  size INTEGER,
  filled_size INTEGER,
  remaining_size INTEGER,
  average_fill_price DOUBLE,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  broker TEXT,
  session_id TEXT,
  trace_id TEXT,
  metadata JSON
);

CREATE TABLE IF NOT EXISTS order_state_transitions (
  order_id TEXT,
  from_status TEXT,
  to_status TEXT,
  ts TIMESTAMP,
  reason TEXT,
  session_id TEXT
);

CREATE TABLE IF NOT EXISTS fills (
  fill_id TEXT,
  order_id TEXT,
  client_order_id TEXT,
  market_ticker TEXT,
  side TEXT,
  action TEXT,
  price DOUBLE,
  size INTEGER,
  fee DOUBLE,
  liquidity TEXT,
  ts TIMESTAMP,
  session_id TEXT
);

CREATE TABLE IF NOT EXISTS positions (
  market_ticker TEXT,
  yes_contracts INTEGER,
  no_contracts INTEGER,
  average_yes_price DOUBLE,
  average_no_price DOUBLE,
  realized_pnl DOUBLE,
  unrealized_pnl DOUBLE,
  updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
  ts TIMESTAMP,
  realized_pnl DOUBLE,
  unrealized_pnl DOUBLE,
  gross_exposure DOUBLE,
  net_exposure DOUBLE,
  session_id TEXT
);

CREATE TABLE IF NOT EXISTS health_events (
  ts TIMESTAMP,
  component TEXT,
  status TEXT,
  detail TEXT,
  session_id TEXT
);

CREATE TABLE IF NOT EXISTS kill_switch_events (
  ts TIMESTAMP,
  state TEXT,
  reason TEXT,
  session_id TEXT
);

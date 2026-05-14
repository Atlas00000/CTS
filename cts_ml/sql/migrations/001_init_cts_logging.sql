-- CTS Phase 2 Week 4 — DDL aligned with Include/CTS_LogCsv.mqh CSV headers (schema v1).
-- Tables: cts_signals (CTS_SIGNALS_*.csv), cts_orders (CTS_EXECUTIONS_*.csv).
-- Re-run on an existing DB: psql <this file> (CREATE IF NOT EXISTS is idempotent).

CREATE TABLE IF NOT EXISTS cts_signals (
  id                BIGSERIAL PRIMARY KEY,
  schema_version    SMALLINT NOT NULL,
  ts_gmt            TIMESTAMPTZ NOT NULL,
  symbol            TEXT NOT NULL,
  tf                TEXT NOT NULL,
  bar_time          BIGINT NOT NULL,
  open1             DOUBLE PRECISION NOT NULL,
  high1             DOUBLE PRECISION NOT NULL,
  low1              DOUBLE PRECISION NOT NULL,
  close1            DOUBLE PRECISION NOT NULL,
  ema_fast_1        DOUBLE PRECISION NOT NULL,
  ema_slow_1        DOUBLE PRECISION NOT NULL,
  macd_main1        DOUBLE PRECISION NOT NULL,
  macd_sig1         DOUBLE PRECISION NOT NULL,
  atr1              DOUBLE PRECISION NOT NULL,
  spread_points     DOUBLE PRECISION NOT NULL,
  bias_long         BOOLEAN NOT NULL,
  bias_short        BOOLEAN NOT NULL,
  sig_long          BOOLEAN NOT NULL,
  sig_short         BOOLEAN NOT NULL,
  skip_reason       TEXT NOT NULL DEFAULT '',
  would_trade       BOOLEAN NOT NULL,
  signal_id         TEXT NOT NULL
);

COMMENT ON TABLE cts_signals IS 'One row per EA signal-bar evaluation; mirrors CTS_SIGNALS_*.csv (§11.4).';
COMMENT ON COLUMN cts_signals.bar_time IS 'Unix seconds from iTime(work_sym, work_tf, 1); broker/server time, not necessarily UTC.';
COMMENT ON COLUMN cts_signals.ts_gmt IS 'UTC wall time when row was written (EA TimeGMT).';

CREATE INDEX IF NOT EXISTS idx_cts_signals_symbol_bar_time ON cts_signals (symbol, bar_time);
CREATE INDEX IF NOT EXISTS idx_cts_signals_signal_id ON cts_signals (signal_id);
CREATE INDEX IF NOT EXISTS idx_cts_signals_ts_gmt ON cts_signals (ts_gmt);

CREATE TABLE IF NOT EXISTS cts_orders (
  id                BIGSERIAL PRIMARY KEY,
  schema_version    SMALLINT NOT NULL,
  ts_gmt            TIMESTAMPTZ NOT NULL,
  signal_id         TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  tf                TEXT NOT NULL,
  side              TEXT NOT NULL,
  volume            DOUBLE PRECISION NOT NULL,
  sl                DOUBLE PRECISION NOT NULL,
  tp                DOUBLE PRECISION NOT NULL,
  retcode           INTEGER NOT NULL,
  deal_ticket       BIGINT NOT NULL,
  deal_time_gmt     TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE cts_orders IS 'Successful market sends; mirrors CTS_EXECUTIONS_*.csv (deal_ticket, retcode).';
COMMENT ON COLUMN cts_orders.deal_ticket IS 'MQL trade ResultDeal() or fallback ResultOrder() as written to CSV.';

CREATE INDEX IF NOT EXISTS idx_cts_orders_signal_id ON cts_orders (signal_id);
CREATE INDEX IF NOT EXISTS idx_cts_orders_ts_gmt ON cts_orders (ts_gmt);
CREATE INDEX IF NOT EXISTS idx_cts_orders_symbol_ts ON cts_orders (symbol, ts_gmt);

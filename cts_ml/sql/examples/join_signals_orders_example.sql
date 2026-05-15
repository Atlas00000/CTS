-- Phase 3 Week 1 — example join: cts_signals ⟕ cts_orders on signal_id
--
-- Edit the literal in `params` below, then run in psql, DBeaver, or:
--   docker compose exec -T postgres psql -U cts_user -d ctsdb -f sql/examples/join_signals_orders_example.sql
--
-- Find candidates: SELECT signal_id FROM cts_signals ORDER BY ts_gmt DESC LIMIT 5;
-- Verified row from tester CSV (2026-01-13 execution sample): EURUSD_PERIOD_M5_1768280100

WITH params AS (
  SELECT 'EURUSD_PERIOD_M5_1768280100'::text AS signal_id
)
SELECT
  s.signal_id,
  s.ts_gmt          AS signal_ts_gmt,
  s.symbol,
  s.tf,
  s.bar_time,
  s.would_trade,
  s.sig_long,
  s.sig_short,
  o.id              AS order_row_id,
  o.ts_gmt          AS order_ts_gmt,
  o.side,
  o.volume,
  o.sl,
  o.tp,
  o.retcode,
  o.deal_ticket,
  o.deal_time_gmt,
  (o.signal_id IS NOT NULL) AS has_fill
FROM params p
JOIN cts_signals s ON s.signal_id = p.signal_id
LEFT JOIN cts_orders o ON o.signal_id = s.signal_id;

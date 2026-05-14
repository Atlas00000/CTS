-- Phase 2 Week 5 — support INSERT ... ON CONFLICT DO NOTHING in the CSV loader.
-- Safe to re-run on existing databases.

CREATE UNIQUE INDEX IF NOT EXISTS uq_cts_signals_signal_id ON cts_signals (signal_id);

-- Deal / order ticket is unique per account; used for idempotent execution loads.
CREATE UNIQUE INDEX IF NOT EXISTS uq_cts_orders_deal_ticket ON cts_orders (deal_ticket);

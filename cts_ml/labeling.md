# CTS — Labeling & join spec (Phase 3 Week 1)

**Audience:** whoever builds `build_dataset.py` (Week 2). **Scope:** `schema_version = 1` tables `cts_signals` / `cts_orders` (see `sql/migrations/001_init_cts_logging.sql`).

---

## 1. Join key: `signal_id`

**Format (EA):** `SYMBOL + "_" + PERIOD_ENUM + "_" + bar_time_unix`

- **`bar_time_unix`:** `iTime(work_sym, work_tf, 1)` cast to integer — **open time of the evaluated closed bar** (broker server time), not `ts_gmt`.
- **Source of truth:** `Include/CTS_LogCsv.mqh` — `CTS_LogCsv_MakeSignalId()`.
- **Stability:** On each new signal bar, `OnTick` builds **one** `signal_id`, logs the signal row, then passes the **same** string into `CTS_TryOpen` → execution row. Signal and execution rows for a given attempt share an identical `signal_id`.

**Postgres:** `cts_signals.signal_id` and `cts_orders.signal_id` are both `TEXT NOT NULL`; join with `s.signal_id = o.signal_id`.

---

## 2. Row grain

| Table | Grain |
|-------|--------|
| `cts_signals` | One row per **new bar** on the signal timeframe when logging is on (see `AI_integration.md` §11.2), whether or not a trade is taken. |
| `cts_orders` | At most **one** row per successful `OrderSend` path logged from `CTS_LogCsv_AppendExecutionRow` (successful market send with `deal_ticket` / `retcode`). **No partial-fill split** in v1 CSV — MT5 aggregate fill is one logged row. |

**Cardinality:** Expect **0 or 1** `cts_orders` row per `signal_id` for normal operation. If you ever see **>1**, treat as data bug or duplicate CSV load (migrations + loader use `ON CONFLICT DO NOTHING` on unique keys — investigate).

---

## 3. Missing execution row (signal without order)

Possible reasons when `would_trade = true` in `cts_signals`:

- Guards / cooldown / spread / risk / stops validation failed **after** the signal row was written.
- `OrderSend` failed (see journal; no execution row).
- `InpLogOrders` was **false** while `InpLogSignals` was true — **orders never written**; join will not see fills. **Labeling requires** `InpLogOrders = true` for any outcome tied to real fills.

When `would_trade = false`, **no** order row is expected from that bar’s signal path (EA does not call `CTS_TryOpen` for conflicting/no setup).

---

## 4. Time fields (do not mix)

| Field | Meaning |
|-------|--------|
| `cts_signals.ts_gmt` | UTC wall clock when the **signal** CSV line was written. |
| `cts_orders.ts_gmt` | UTC wall clock when the **execution** CSV line was written (immediately after send in EA). |
| `cts_orders.deal_time_gmt` | In **schema v1 EA**, written as the **same** instant as `ts_gmt` on that row — **not** a separate `HistoryDealGetTime` pull. If you need true deal time for labels, plan a **schema bump** or an MT5 **history export** joined by `deal_ticket`. |
| `cts_signals.bar_time` | Unix seconds, **broker** open time of the signal candle — use for aligning to bar-based features and external bar data. |

---

## 5. Label definitions (pick one for v1 training)

### 5.A Join / coverage label (no extra EA fields)

**`has_fill`:** `EXISTS (SELECT 1 FROM cts_orders o WHERE o.signal_id = s.signal_id)`.

Useful for modeling **whether a `would_trade` signal results in a logged fill** under current guards and logging. Does **not** encode profitability.

### 5.B Risk / reward label (recommended direction — needs price at entry)

**`hit_plus_1R_before_minus_1R` (example):** fixed horizon or first-touch in **price** space relative to **entry** and **initial SL** distance.

**Blocker for strict v1:** `cts_orders` stores `sl`, `tp`, `volume`, `side` but **not** the actual **fill / entry price**. For a proper R-multiple label you need at least one of:

1. **Schema v2:** add `entry_price` (and optionally `fill_time`) to `CTS_EXECUTIONS_*.csv` + `cts_orders` + loader (defer to Week 2 if you choose this path), or  
2. **Offline MT5 export** of deals keyed by `deal_ticket`, joined in Python or SQL.

Until then, any “+1R” label using **signal bar `close1`** as a **proxy entry** must be documented as **approximate** (gap/slippage not modeled) and not mixed with strict execution labels.

### 5.C **Locked for v1 (Week 1 complete)**

**Training subset:** rows with **`would_trade = true`** (single-direction signal only; EA skips `both_signals`).

**Target column for Week 2 (`y` or `y_has_fill`):**

```text
y_has_fill = EXISTS (matching cts_orders row for the same signal_id)
```

i.e. **`has_fill`** as defined in §5.A. **Horizon:** N/A (not a time-based outcome label). **Entry / PnL:** not used until **`entry_price`** (schema v2) or deal export (§5.B).

All other rows ( `would_trade = false` ) may still be kept for **unsupervised** or **counterfactual** work later; the **first supervised baseline** uses the subset above unless you document otherwise.

---

## 6. Example query & Week 2–3 pipeline

- **Ad hoc join:** `sql/examples/join_signals_orders_example.sql`.
- **Week 2 dataset:** `python scripts/build_dataset.py` — same join and **`y_has_fill`**; default export = **`would_trade = true`** rows only (`README.md` Phase 3 Week 2).
- **Week 3 baseline:** `python scripts/train_baseline.py` — time-ordered split + sklearn RF/logistic on that Parquet (`README.md` Phase 3 Week 3).
- **Week 6 (optional):** `augment_regime_column.py` + `train_regime_model.py` — **`regime_rule_v1`** + multiclass RF (`README.md` Phase 3 Week 6).


---

## 7. Week 1 exit check (from `AI_integration.md` §5.5)

- [x] This file is unambiguous on **label definition**, **horizon** (N/A for `has_fill`), and **entry reference** (not used for `y_has_fill` in v1).
- [x] Example SQL runs in `psql` against `ctsdb` after CSV load; returns one `signal_id` row with **`has_fill`**.

---

## 8. Week 1 verification log (host)

| Check | Result |
|-------|--------|
| CSV glob | `MetaQuotes\Tester\…\Agent-127.0.0.1-3000\MQL5\Files\CTS_logs_tester\CTS_SIGNALS_*.csv` and `CTS_EXECUTIONS_*.csv` |
| `load_csv_to_postgres.py` | Completed: `signals read=26991 inserted=20678`; `orders read=33 inserted=24` (remainder = prior duplicates / `ON CONFLICT DO NOTHING`) |
| `SELECT COUNT(*)` | `cts_signals` **26992**; `cts_orders` **34** |
| Join smoke | `INNER JOIN` on **`EURUSD_PERIOD_M5_1768280100`** matches tester `CTS_EXECUTIONS_2026-01-13.csv` (`deal_ticket=6`, `sl`/`tp` as logged). |
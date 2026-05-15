# CTS — Labeling & join spec (Phase 3 Week 1)

**Audience:** whoever builds `build_dataset.py` (Week 2). **Scope:** `cts_signals` rows remain **CSV schema v1** (`schema_version = 1`). `cts_orders` rows may be loaded from **execution CSV v1** (no `entry_price` column; `schema_version = 1`) or **v2** (adds `entry_price`; `schema_version = 2` in the CSV). See `sql/migrations/001_init_cts_logging.sql` + `003_cts_orders_entry_price.sql`.

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
| `cts_orders` | At most **one** row per successful `OrderSend` path logged from `CTS_LogCsv_AppendExecutionRow` (successful market send with `deal_ticket` / `retcode`). **No partial-fill split** in CSV — MT5 aggregate fill is one logged row. **Execution CSV v2** adds **`entry_price`** (ASK for BUY, BID for SELL at send) for strict R-multiple labels. |

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

### 5.B Risk / reward label (needs price at entry)

**`hit_plus_1R_before_minus_1R` (example):** first-touch in **price** space relative to **entry** and **initial SL** distance (needs bar or tick path **after** entry — implement offline in Python, not in the EA logger).

**Strict path (execution CSV v2 + DB):** `cts_orders.entry_price` is populated from **`CTS_EXECUTIONS_*.csv` v2** (`Include/CTS_LogCsv.mqh`, `CTS_EXEC_CSV_SCHEMA_VERSION = 2`). Joined into the Parquet column **`fill_entry_price`** (`build_dataset.py`). With **`side`**, **`entry_price`**, and **`sl`**, define initial stop distance in **price** (not points):

- **BUY:** \(R_{\text{price}} = \texttt{entry\_price} - \texttt{sl}\) (positive when SL is below entry).
- **SELL:** \(R_{\text{price}} = \texttt{sl} - \texttt{entry\_price}\).

Then **`+1N`** levels are **`entry_price ± N * R_price`** (sign by side). **Tester vs live:** logged price is the EA’s quote at send; slippage on the filled deal is **not** in v2 CSV unless you add a **deal export** keyed by `deal_ticket`.

**Legacy execution CSV v1:** `entry_price` is missing → **`fill_entry_price`** is null in the dataset. For approximate labels only, **`close1`** from the signal row may be used as a **proxy entry** — document as **approximate** and do not mix with strict v2 execution labels in the same benchmark.

### 5.C **Locked for v1 (Week 1 complete)**

**Training subset:** rows with **`would_trade = true`** (single-direction signal only; EA skips `both_signals`).

**Target column for Week 2 (`y` or `y_has_fill`):**

```text
y_has_fill = EXISTS (matching cts_orders row for the same signal_id)
```

i.e. **`has_fill`** as defined in §5.A. **Horizon:** N/A (not a time-based outcome label). **Entry / PnL:** primary baseline still does **not** require **`fill_entry_price`**; use §5.B when you add R / outcome targets.

All other rows ( `would_trade = false` ) may still be kept for **unsupervised** or **counterfactual** work later; the **first supervised baseline** uses the subset above unless you document otherwise.

### 5.D **Dataset-derived R geometry + 1-bar proxy (optional, not Phase 3 default `y`)**

`build_dataset.py` adds (when order fields exist):

| Column | Meaning |
|--------|--------|
| **`fill_side`**, **`fill_sl`**, **`fill_tp`** | From latest `cts_orders` row for `signal_id` (same LATERAL as `fill_entry_price`). |
| **`forward_close_1`** | `close1` of the **next logged signal row** for the same **`symbol` + `tf`** with strictly greater **`bar_time`** (broker time). **Not** the deal close; use for crude **1-bar** probes only. |
| **`initial_r_price`**, **`plus_1r_price`**, **`minus_1r_price`** | §5.B geometry in **price** units; **NaN** if `fill_entry_price` missing (legacy execution CSV) or invalid / non‑BUY‑SELL side or \(R \le 0\). |
| **`y_proxy_1bar_close_ge_plus_1r`** | **1.0 / 0.0 / NaN:** compares **`forward_close_1`** to **`plus_1r_price`** (BUY: close ≥ +1R; SELL: close ≤ +1R). Uses **close**, not **high/low** path — **not** “first touch +1R before −1R”; do **not** treat as equivalent to a strict intrabar outcome label. |

Use **`y_proxy_*`** only in **experimental** models; keep **`y_has_fill`** as the locked production-aligned target until you add tick/deal path labels.

---

## 6. Example query & Week 2–3 pipeline

- **Ad hoc join:** `sql/examples/join_signals_orders_example.sql`.
- **Week 2 dataset:** `python scripts/build_dataset.py` — **`y_has_fill`**, **`fill_*`** order columns, **`forward_close_1`**, R geometry (**`initial_r_price`**, **`plus_1r_price`**, **`minus_1r_price`**), optional **`y_proxy_1bar_close_ge_plus_1r`** (§5.D); default **`would_trade = true`** (`README.md` Phase 3 Week 2).
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
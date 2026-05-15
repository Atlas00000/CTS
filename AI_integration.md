# CTS — Logging & AI Integration Design

**Purpose:** This document turns the ideas in *AI-Enhanced MT5 Trading System Architecture (1).md* into a **concrete, minimal-scope plan** for the existing **CTS** Expert Advisor. Phase 1 (deterministic execution engine) is **complete**. What follows is **structured logging first**, then **offline ML**, then **optional live filtering**—without overengineering.

**Scope guardrails (unchanged from `concept.md`):**

- AI **filters or scores** setups; it does **not** replace the deterministic entry rules unless you explicitly decide that later.
- No distributed systems, message buses, Kubernetes, or live model training inside MT5.
- No LLM for numerical signal scoring (use tabular ML when you add AI).
- **Canonical store:** **PostgreSQL** for queryable, multi-run datasets and training pulls. Run the database in **Docker** (e.g. `docker compose` in `cts_ml/`) so you **do not** need a native Postgres install on Windows—expose it on **`127.0.0.1:<port>`** and point `POSTGRES_DSN` there. The EA still **captures via CSV** (or JSONL) under `MQL5/Files/` first—**MQL5 has no first-class Postgres driver**—then **host-local Python** loads into Postgres on a schedule or after session. Keep one clear pipeline: *write fast in MT5 → bulk load in Python → Postgres in Docker*.

---

## 1. Current foundation (Phase 1 — done)

**Delivered in code:**

- Modular MQL5: `CTS_Config`, `CTS_Log`, `CTS_State`, `CTS_Indicators`, `CTS_Signals`, `CTS_Risk`, `CTS_Trade`, orchestration in `CTS.mq5`.
- Deterministic Classic Trend Stack: closed-bar bias, EMA cross `2→1`, MACD main/signal cross `2→1`, new-bar-only evaluation.
- Execution: market orders, magic, spread/equity/direction guards, position caps, cooldown, SL/TP (fixed / ATR / RR), risk-percent sizing with normalization.

**This document assumes:** that stack remains the **source of truth** for *when* a setup exists; later phases only add **observation**, **datasets**, and **optional gating/scoring**.

---

## 2. Design principles (infusion phases)

| Principle | Meaning for CTS |
|-----------|-----------------|
| **Deterministic first** | Logging and ML learn from the **same** rules the EA already uses; baseline backtests stay interpretable. |
| **Loose coupling** | EA writes **files** or **simple HTTP** to a local service; no hard dependency on Python for the EA to compile or run in “baseline” mode. |
| **Fail-safe** | If logging fails → skip log line, **do not** block trading. If AI service is down → **default = act like Phase 1** (trade) or **default = skip**—pick one policy and document it in inputs. |
| **Tester-aware** | Strategy Tester may disable file paths or network; logging mode must support **OFF / FILE / MOCK** without crashing. |
| **No feature explosion** | Log only fields you will **actually** use in the first model (see §4). Add columns in versioned steps, not fifty at once. |

---

## 3. High-level architecture (target)

```
                    ┌─────────────────────────────────────┐
                    │           MT5 — CTS EA              │
                    │  Indicators → Signals → Risk/Trade  │
                    └───────────────┬─────────────────────┘
                                    │
                    ┌───────────────▼───────────────────────┐
                    │   Logging layer (Phase 2)            │
                    │   signal rows + optional trade rows   │
                    └───────────────┬───────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
   CSV in MQL5/Files   PostgreSQL in Docker    FastAPI on host (Phase 4+)
   (capture, default)   (Python COPY/INSERT)    (inference / optional ingest)
              │                     │                     │
              └─────────────────────┴─────────────────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────────────┐
                    │   Offline Python (Phase 3)          │
                    │   train / validate / export model   │
                    └───────────────┬─────────────────────┘
                                    │
                                    ▼
                    ┌─────────────────────────────────────┐
                    │   Inference (Phase 4, optional)     │
                    │   score → allow / size / skip         │
                    └─────────────────────────────────────┘
```

**Data vs scoring paths (read this once):** **Training data** flows *sequentially* — MT5 writes **CSV** → **host-local Python** **bulk-loads** → **PostgreSQL (Docker)** → Phase 3 reads with SQL/pandas. **Phase 4** **FastAPI runs on the host** (not in Docker by default): serves an **exported model from disk** (and optional mock file in tester); it does **not** need to query Postgres on every tick (keeps inference simple and fast). EA **`WebRequest`** targets **`http://127.0.0.1:...`** only.

### 3.1 Technology stack (by phase, goal-aligned)

| Phase | Goal | Stack (keep this set small) |
|-------|------|-----------------------------|
| **1** (done) | Deterministic entries + risk | **MT5**, **MQL5**, `<Trade/Trade.mqh>` — no Python/DB required to run the EA. |
| **2** | Capture + durable store for ML | **MQL5** file I/O → **CSV** (or JSONL) under `MQL5/Files/`; **Python 3** on the **host** + **`psycopg`** (v3) or **SQLAlchemy** + **PostgreSQL inside Docker** (`localhost` mapped port); **pandas** or **polars** for validation joins; **Jupyter** optional for spot checks. |
| **3** | Offline train / validate / export | Reads from **Postgres (Docker)** or CSV bootstrap—all scripts/notebooks **host-local**; **pandas/polars**; **scikit-learn**; **one** primary boosted tree library (**XGBoost** *or* **LightGBM**, not both until you need the second); export **ONNX** *or* **native** model format — pick one in §5.3 and keep it; **Git** + pinned **`requirements.txt`**. |
| **4** | Optional live filter / shadow score | **FastAPI** + **uvicorn** on the **host** at **127.0.0.1** (default: **not** containerized—easier MT5 `WebRequest`, direct paths to CSV/model); EA **`WebRequest`**; model artifact on disk; **no Postgres on hot path** unless you explicitly add a lookup later. |
| **5** | Simple adaptive thresholds | Same as Phases 3–4 + **versioned config** (YAML/env); still **no** online learning in-terminal; retrain offline on schedule. |

**Dependency principle:** every new library must answer: *“Which phase milestone needs this?”* If it does not support logging (2), training (3), or inference (4), defer it.

### 3.2 Runtime topology — Docker vs host (local)

| Piece | Where it runs | Why |
|-------|----------------|-----|
| **MT5 + CTS EA** | Your machine (terminal) | Broker execution; writes CSV under `MQL5/Files/`. |
| **PostgreSQL** | **Docker** (`cts_ml/docker-compose.yml` or equivalent) | No local Postgres server install; reproducible version; data on a **named volume**. Bind to **`127.0.0.1:5432`** (or another port) for host tools only. |
| **Other services (optional)** | **Docker** when they fit the same pattern | e.g. **pgAdmin** image, object store—add **only** if needed; keep the compose file small. |
| **Python: load scripts, training, notebooks** | **Host** (venv / system Python) | Simple paths to terminal `Files` and logs; `psycopg` connects to `localhost` → container. |
| **Python: FastAPI inference (Phase 4)** | **Host** (`uvicorn` on `127.0.0.1`) **by default** | EA `WebRequest` to localhost; trivial debugging. **Optional later:** Dockerize the API for a second machine—**not** required for v1. |

**Rule of thumb:** **Docker for stateful / “install me” pieces (Postgres, optional tools).** **Host-local for the moving parts you edit daily (Python backend, training).**

**Non-goals for this roadmap:** multi-tenant cloud APIs, real-time feature stores, auto-retraining pipelines in production, RL/transformers for execution scoring, HA Postgres clusters (a **single** Postgres **container** (or compose service) on **localhost** is enough until proven otherwise).

---

## 4. Phase 2 — Proper logging (next)

### 4.1 Objectives

- Build a **repeatable dataset** of every **signal evaluation** (at minimum: each new bar on the signal timeframe) and every **order outcome** you care about for labeling.
- Keep **latency and I/O** bounded: buffered writes, flush on `OnDeinit` or timer, not thousands of tiny disk hits per second.

### 4.2 What to log (minimal v1 schema)

**A. Signal / decision row (one per new-bar evaluation, or one per “would trade” if you need smaller files—choose explicitly)**

Suggested columns (extend later with a `schema_version` column):

| Column | Description |
|--------|-------------|
| `schema_version` | Integer, start at `1`. |
| `ts_gmt` | UTC wall time when the row is **written** (`TimeGMT()` in EA). |
| `symbol` | Work symbol. |
| `tf` | Signal timeframe enum string. |
| `bar_time` | **Broker/server** open time of signal bar at shift `1` (`iTime(...,1)`). See **§11.1** (not necessarily UTC). |
| `open1, high1, low1, close1` | OHLC of signal bar (optional but useful for offline features). |
| `ema_fast_1, ema_slow_1` | Values at shift 1 (rename in log to match reality vs “50/200” naming). |
| `macd_main1, macd_sig1` | Same. |
| `atr1` | ATR at shift 1. |
| `spread_points` | At evaluation. |
| `bias_long, bias_short` | Booleans from same rules as signals (or skip and derive offline). |
| `sig_long, sig_short` | Final boolean results of `CTS_ShouldEnterLong` / `Short`. |
| `skip_reason` | Empty if no signal; else first gate (e.g. “both signals”). |
| `would_trade` | True if a market order would be attempted after guards (optional duplicate of sig_* caps). |
| `signal_id` | Stable string ID for joins signal ↔ execution ↔ outcome (see **§11.5**). |

**B. Execution row (when an order is sent)**

| Column | Description |
|--------|-------------|
| Same ids as above + `ticket`, `side`, `volume`, `sl`, `tp`, `retcode`, `deal_time` (when known). |

**C. Outcome row (for ML labels — Phase 2b or 3)**

- Simplest approach: **offline script** joins execution data (**Postgres `cts_orders`** and/or **CSV**) with exported deals history from MT5; EA does not need to track full PnL in Phase 2 if that adds complexity.
- Optional later: on position close, append `pnl_money`, `pnl_points`, `mfe`, `mae` if you can compute cheaply from MT5 history.

### 4.3 Implementation notes (MQL5)

- New module: e.g. `Include/CTS_LogCsv.mqh` (or extend `CTS_Log.mqh` if small).
- **File location:** `MQL5/Files/<subdir>/` relative to the **active sandbox**: **live/visual** → `MetaQuotes/Terminal/<id>/MQL5/Files/` (default subdir `CTS_logs`); **Strategy Tester** → `MetaQuotes/Tester/<id>/Agent-*/MQL5/Files/` (when `InpLogInTester`, default subdir `CTS_logs_tester`). See `cts_ml/README.md` §EA CSV output.
- **Input group:** `InpLogCsv`, path prefix, flush interval, `InpLogSignals` / `InpLogOrders` toggles.
- **Tester:** If `MQLInfoInteger(MQL_TESTER)` is true, default logging **OFF** or to a dedicated tester subfolder with size cap—avoid huge optimizations.
- **Threading:** MQL5 is single-threaded; use `FileOpen` with `FILE_TXT|FILE_READ|FILE_WRITE|FILE_ANSI` (see **§11.3**); append via `FileSeek(..., SEEK_END)` for same-day file; periodic flush / flush on `OnDeinit`.

### 4.3b PostgreSQL (system of record)

- **Role:** Durable tables for `cts_signals`, `cts_orders`, later `cts_outcomes` (or one wide table per `schema_version`—pick early and migrate with SQL scripts).
- **Why Postgres:** SQL for ad-hoc analysis, indexes on `(symbol, bar_time)`, easy joins for labels, tooling (pgAdmin, Metabase, etc.), and a single place for Python training to `SELECT` without parsing thousands of CSVs by hand.
- **Docker runtime:** Use a **`docker-compose.yml`** in `cts_ml/` with the official **`postgres`** image (pin a major.minor tag). Map **`127.0.0.1:${POSTGRES_PORT:-5432}:5432`**, use a **named volume** for `PGDATA`, and pass `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` via **`.env`** (gitignored). Start with `docker compose up -d`; document this in a short `cts_ml/README.md`. No native Postgres installation on the host.
- **How data gets there (recommended):** **Host-local** Python script `scripts/load_csv_to_postgres.py` using `psycopg` / SQLAlchemy + `COPY ... FROM STDIN` or batched `INSERT` after terminal closes or on a timer; DSN like `postgresql://user:pass@127.0.0.1:5432/ctsdb`. **Do not** embed DB credentials in the EA; connection strings live in env vars or `configs/` outside git.
- **Optional later:** If you need near–real-time rows, add a minimal **host-local** FastAPI **ingest** endpoint that accepts POSTed JSON batches from a **separate** small client or manual upload—still avoid wiring raw Postgres from MQL5.
- **Ops baseline:** One database, one DB user with least privilege; backup via `docker exec … pg_dump` or volume snapshots; version schema with numbered `.sql` files under `cts_ml/sql/`.

### 4.4 Phase 2 exit criteria

- [x] One CSV per run (or per day) with stable header and `schema_version`; Postgres tables match the same columns after load (`scripts/load_csv_to_postgres.py` + `sql/migrations/001`).
- [x] Live and visual mode: logging on does not materially delay ticks (batch writes in EA unchanged; loader is **offline**).
- [x] Documented clock (server vs GMT) and bar time definition matches shift `1` logic in code (`cts_ml/README.md` §11.1, `AI_integration.md` §11).
- [x] You can rebuild the same logical dataset from **PostgreSQL** and/or raw CSV **without** tribal knowledge (`configs/.env.example`, `cts_ml/README.md` Week 5 runbook).

### 4.5 Weekly implementation plan (Phase 2 — proper logging)

Work **in order**; each week should end with something you can **demo or verify** (file exists, row count grows, or load script succeeds). Merge weeks if your schedule is tight—do **not** skip exit checks in §4.4.

| Week | Focus | Deliverables | Exit (that week) |
|------|--------|--------------|------------------|
| **1** | **Spec + wiring shell** | Freeze **v1** column list and `schema_version`; add **input group**; create `Include/CTS_LogCsv.mqh` with **header write** + optional **test row** from `OnInit`; document **§11.1** time rules in `cts_ml/README.md`. | EA compiles; log **off** = zero file I/O; log **on** = `CTS_SIGNALS_YYYY-MM-DD.csv` with **§11.4** header under `MQL5/Files/<subdir>/`. |
| **2** | **Signal rows (new bar)** | On **each new bar** of the signal TF, append **one signal row** per §4.2A / §11.4 (`CTS_LogCsv_AppendSignalRow`); buffered write + flush per row; UTC **day rollover** reopens file. | **Done in code (v1.03):** one row per bar including **both_signals** / no-signal cases; `signal_id` + OHLC + biases. |
| **3** | **Tester + execution rows** | Default **`MQL_TESTER`** → logging **OFF** or subfolder + **row cap** input to avoid huge optimizations; when ON, same schema. On **successful** `CTS_OpenMarket` / send path, append **execution row** §4.2B (`ticket`, side, volume, SL/TP, `retcode`, wall time). | **Done in code (v1.04+):** `InpLogInTester` / `InpLogTesterSubdir` / `InpLogTesterMaxRows`; `CTS_EXECUTIONS_<UTCday>.csv` when `InpLogOrders`; execution `signal_id` matches signal rows; tester cap counts signal + execution rows. **v1.07:** execution CSV **v2** adds **`entry_price`** (ASK/BID at send) for offline R labels; **`003_cts_orders_entry_price.sql`** + loader accept legacy v1 execution files. |
| **4** | **Docker Postgres + DDL** | Add **`cts_ml/docker-compose.yml`** + **`.env.example`**; `sql/migrations/001_init_cts_logging.sql` for `cts_signals` / `cts_orders` (or one table + `row_type`—match your CSV); `docker compose up -d`; verify `psql` or GUI from host to `127.0.0.1`. | **Done (repo):** Compose `postgres:16.6-bookworm`, `127.0.0.1` bind, named volume, init DDL from `sql/migrations/001_init_cts_logging.sql`; `cts_ml/README.md` runbook + `\dt` / re-apply notes. **Local exit:** `docker compose up -d` + `psql` succeeds on your machine. |
| **5** | **Load pipeline + hardening** | Implement **`scripts/load_csv_to_postgres.py`**: idempotent append or run-id column; `COPY` or batched insert; document **DSN** in `configs/.env.example`; README: compose up, load command, **backup** (`pg_dump` / volume). **Performance pass:** batch size, flush interval; confirm tick path still “light.” | **Done (repo):** batched multi-row `INSERT … ON CONFLICT DO NOTHING` (`002` unique indexes); `configs/.env.example`; `requirements.txt`; README runbook; EA tick path unchanged (loader offline). **Local exit:** `pip install -r requirements.txt` + load a real CSV + `SELECT COUNT(*)`. |

**Optional buffer week:** file rotation (daily file), maximum file size input, or **gzip** archive of closed CSVs before load—only if Week 5 already met criteria and you still see disk pressure.

---

## 5. Phase 3 — Offline AI (Python, no EA dependency)

### 5.1 Objectives

- Answer: *“When CTS fires a signal, what contexts are historically worth taking?”* using **tabular ML** (e.g. XGBoost / LightGBM / sklearn RandomForest)—aligned with the architecture template.
- **Train only offline** on data **read from PostgreSQL** (preferred once loaded) or directly from CSV + optional MT5 deal exports during bootstrap.

### 5.2 First models (strict order)

1. **Binary classifier:** “profitable vs not” (or “hit +1R vs not”) at a fixed horizon—define label precisely in a one-page `labeling.md` when you start (avoid ambiguous labels).
2. **Regime helper (optional second model):** trending vs chop **derived from features you already log**, not new indicators in the EA until needed.

### 5.3 Deliverables

- `notebooks/` or `scripts/`: **pull from PostgreSQL** (or CSV during bootstrap) → clean → split by time (**walk-forward**, no random shuffle across time) → train → calibration curve → **export model** (JSON + native lib, or ONNX if you standardize—pick one path and stay with it).
- **Feature list frozen** for v1 to match Phase 2 columns; new features = new `schema_version`.

### 5.4 Phase 3 exit criteria

- [x] Reproducible training script + pinned **`requirements.txt`** (include **Postgres client** + **pandas**/**polars** + **sklearn** + chosen **XGBoost or LightGBM**).
- [x] Out-of-sample metrics documented; no claim of live profitability without forward test.
- [x] Exported artifact + **inference snippet** that loads the model and scores one row (used by Phase 4).

### 5.5 Weekly implementation plan (Phase 3 — offline ML)

Work **in order**; each week should end with something you can **demo** (script runs, metrics file, or exported artifact). Merge weeks if your schedule is tight—do **not** skip exit checks in §5.4.

| Week | Focus | Deliverables | Exit (that week) |
|------|--------|--------------|------------------|
| **1** | **Label + join spec** | Repo: **`cts_ml/labeling.md`** + **`cts_ml/sql/examples/join_signals_orders_example.sql`** — **`y_has_fill`** (§5.C), optional **R / PnL** targets when **`fill_entry_price`** / **`cts_orders.entry_price`** is present (execution CSV v2), **horizon**, **entry reference**, **partial fills** / **missing deals**. | Edit `params` in the example SQL; query returns the chosen `signal_id` row with **`has_fill`**; spec has no ambiguous default label. |
| **2** | **Dataset build** | **`cts_ml/scripts/build_dataset.py`**: Postgres **`cts_signals` ⟕ `cts_orders`**, label **`y_has_fill`**, **`fill_*`** order columns, **`forward_close_1`**, R geometry (**`initial_r_price`**, **`plus_1r_price`**, **`minus_1r_price`**), optional **`y_proxy_1bar_close_ge_plus_1r`** (`labeling.md` §5.D); default **`would_trade = true`**; **Parquet** or **CSV** under **`cts_ml/data/`** (gitignored); **QC**. | `python scripts/build_dataset.py --dry-run` then default write; row count matches `SELECT COUNT(*) FROM cts_signals WHERE would_trade`; no duplicate **`signal_id`**. |
| **3** | **Walk-forward + baseline** | **`cts_ml/scripts/train_baseline.py`**: sort **`ts_gmt`**; split **`configs/baseline_split_v1.yaml`** (by row index after sort) + optional **`purge_hours`**; **`RandomForestClassifier`** or **`LogisticRegression`**; metrics **PR-AUC**, **Brier**, **log_loss**; **`--write-split-config`** to re-freeze YAML; optional **`--out-model`** **`.joblib`** for **`export_phase3_bundle.py`**. | `python scripts/train_baseline.py` on current Parquet prints JSON; validation metrics finite; split YAML committed / updated when row count changes. |
| **4** | **Primary booster** | **`cts_ml/scripts/train_booster.py`**: **XGBoost** (fixed hyperparams + `scale_pos_weight`); same split as Week 3; **RF reference** on validation; **calibration CSV** (`calibration_curve`); **bucket** stats (`symbol`, **ATR quartiles**); artifacts **`*_metrics.json`**, **`*_calibration_val.csv`**, **`*_xgb.joblib`**. Shared split/features: **`scripts/ml_common.py`**. | `python scripts/train_booster.py` completes; JSON reports `comparison` vs RF; calibration + model files exist. “Beats baseline” is **informational** on small `n`. |
| **5** | **Export + handoff** | **`scripts/export_phase3_bundle.py`**: **`model.joblib`** + **`manifest.json`** (features, label ref, versions); optional metrics/calibration → **`cts_ml/exports/phase3_v1/`** (gitignored). **`scripts/inference_score_row.py`**: score one row via **`--row-json`** or **`--from-parquet`**. **`requirements.txt`** pinned tighter + **`joblib`**. Native joblib path only (no ONNX). | Export + inference run; Phase 4 loads **`exports/phase3_v1/model.joblib`**. |
| **6** *(optional)* | **Regime helper** | **`scripts/regime_rules.py`**: **`regime_rule_v1`** (`trend_long` / `trend_short` / `chop`) from logged EMA/MACD/bias. **`scripts/augment_regime_column.py`**: append column to Parquet. **`scripts/train_regime_model.py`**: multiclass **RF** on numeric+`symbol`/`tf` only (excludes bias/sig); same split YAML; **`validation_by_symbol`**; optional **`regime_rf_week6.joblib`**. | Augment + train complete; metrics JSON shows regime counts and val accuracy / macro-F1. |

---

## 6. Phase 4 — AI-assisted execution (optional, minimal)

### 6.1 Objectives

- Optionally call a **local** FastAPI (or single script HTTP) service: send **numeric feature vector** (or small JSON), receive `score` and/or `allow` flag. The service loads the **Phase 3 exported model** from disk; **PostgreSQL is not required** on each request unless you add an explicit feature lookup later.
- **Policy examples (choose one, input-driven):**
  - **Filter:** trade only if `score >= threshold`.
  - **Size:** scale volume by `score` within min/max clamps.
  - **No change:** log score only for shadow mode.

### 6.2 Safety and operations

- **Placement:** Run **FastAPI/uvicorn on the host** at **`127.0.0.1`** (see §3.2). Postgres stays in **Docker**; the EA never opens a DB socket—only HTTP to your local API if you enable Phase 4.
- **Timeout:** hard cap (e.g. 50–200 ms configurable); on timeout → follow **fail-safe policy** (recommend: **skip trade** when AI filter enabled, **log timeout**).
- **Tester:** either disable HTTP or use **mock scores** from file—real HTTP often undesirable in optimization.
- **Secrets:** none in the EA for v1; API binds **`127.0.0.1`** only; DB credentials only in **`.env`** for Docker Compose + host Python DSN.

### 6.3 EA changes (small)

- New module: e.g. `Include/CTS_AiGate.mqh`: build feature struct from existing buffers + optional `WebRequest`.
- Inputs: `InpUseAiFilter`, `InpAiEndpoint`, `InpAiTimeoutMs`, `InpAiThreshold`, `InpAiShadowMode` (log score but do not block).

### 6.4 Phase 4 exit criteria

- [ ] Shadow mode runs live without changing fills vs baseline (only extra log column).
- [ ] Filter mode demonstrably reduces trade count in forward test when intended.
- [ ] No unhandled `WebRequest` errors; connection failures logged and policy applied.

### 6.5 Weekly implementation plan (Phase 4 — local inference)

Optional phase; skip entirely if you stop after **Phase 3**. Work **in order**; each week ends with a **host demo** and/or **EA shadow** check.

| Week | Focus | Deliverables | Exit (that week) |
|------|--------|--------------|------------------|
| **1** | **API skeleton** | **FastAPI** + **uvicorn** on **`127.0.0.1`** only; **`GET /health`**; load **Phase 3 artifact** at startup; config via **env** (model path, threshold defaults). | `curl http://127.0.0.1:<port>/health` returns OK with model loaded. |
| **2** | **Score endpoint** | **`POST /score`** (or `/predict`) accepts small JSON feature vector or **`signal_id`** lookup (if you add optional DB read); returns **`score`** + **`allow`**; strict **timeout** handling; unit test or scripted client. | Local script scores **≥1** real row from Phase 3 dataset in under the configured **timeout** ms. |
| **3** | **Shadow in EA** | Add **`Include/CTS_AiGate.mqh`** + inputs (`InpUseAiFilter`, `InpAiEndpoint`, `InpAiTimeoutMs`, `InpAiThreshold`, `InpAiShadowMode`); **`WebRequest`** to localhost; **shadow mode** logs score **without** changing `CTS_TryOpen` decisions. | Forward / visual run: journal shows scores; **fills match** baseline CTS with filter **off** or shadow **on**. |
| **4** | **Filter policy + hardening** | Enable **filter** path (`score >= threshold`); fail-safe on **timeout / HTTP error** (documented); **tester** path: disable HTTP or **mock scores file** (no real HTTP in optimization). | §6.4 exit criteria: filter changes trade count when intended; no uncaught `WebRequest` errors. |

### 6.5.1 Week-by-week task checklist (Phase 4)

Use this as a **sequenced backlog** under §6.5; each week ends with a concrete demo.

**Week 1 — API skeleton**

- Add a small Python service package (e.g. `cts_ml/phase4_api/`) with **`pyproject.toml`** or **`requirements.txt`** entries: `fastapi`, `uvicorn`, existing `joblib` / `scikit-learn`.
- Bind **`127.0.0.1`** only; port from **env** (e.g. `CTS_AI_PORT`).
- **`GET /health`**: returns JSON with `ok`, `model_path`, `model_loaded` boolean.
- Load **`model.joblib`** at startup from **env** `CTS_PHASE3_MODEL` (path to bundle `model.joblib`); fail fast with clear log if missing.
- Document **`README.md`** Phase 4: how to `uvicorn` from repo root / `cts_ml`.

**Week 2 — Score endpoint**

- **`POST /score`**: body = JSON object whose keys are **`manifest.json` → `feature_columns`** (same names/types as training Parquet row); response = `{ "score": <float 0..1>, "allow": <bool> }` using **positive-class probability** and optional threshold from env.
- Validate missing keys → **422** with list of missing feature names.
- Internal **timeout** budget (e.g. 50 ms CPU work cap per request — document; true wall-clock async timeout optional v1).
- Smoke: `curl` or **`inference_score_row.py`**-style script calling `/score` with one row from **`cts_dataset_*.parquet`**.

**Week 3 — Shadow in EA**

- Add **`Include/CTS_AiGate.mqh`** (+ `CTS.mq5` include): build numeric/bool/cat feature dict from **same buffers** as logging (must match training schema).
- Inputs: **`InpUseAiGate`**, **`InpAiEndpoint`**, **`InpAiTimeoutMs`**, **`InpAiThreshold`**, **`InpAiShadowMode`** (names can vary; behaviour per §6.3).
- **`WebRequest`** POST to localhost; on success log **score** (journal or optional CSV column later); **never** change `CTS_TryOpen` outcome when shadow mode on.
- Verify: with gate **off** vs **shadow on**, trade list / deal count **unchanged** on visual test.

**Week 4 — Filter + hardening**

- When filter mode on: if **`score >= InpAiThreshold`** proceed as baseline; else **skip open** (document exact branch next to `CTS_TryOpen`).
- On **timeout**, **HTTP error**, or malformed JSON: apply **fail-safe** (recommend: skip trade when filter enabled); always **log** reason code.
- Strategy Tester: **`InpAiDisableInTester`** or equivalent so optimization does not depend on HTTP unless using a **mock** file-based scorer (defer mock to “stretch” if needed).

---

## 7. Phase 5 — Adaptive controls (later, still simple)

Only after Phases 2–4 are stable:

- Adjust **threshold** or **risk multiplier** by **regime bucket** (from Phase 3 regime model or simple volatility quartiles from logged ATR).
- Avoid **continuous online learning** in v1; use **periodic manual retrain** with frozen deployment windows.

**Exit criteria:** documented rules for when parameters change and backtest evidence for each change.

### 7.1 Weekly implementation plan (Phase 5 — adaptive controls)

Only start after **Phase 4** (or **Phase 3** + explicit decision to skip live API) is stable. Weeks are **small policy** changes, not new ML architectures.

| Week | Focus | Deliverables | Exit (that week) |
|------|--------|--------------|------------------|
| **1** | **Regime buckets** | Define **buckets** (e.g. ATR quartiles from logged `atr1`, or output of optional Phase 3 regime model); map each live bar to a **bucket id**; document in **`configs/adaptive_v1.yaml`** (or similar). | Bucketing script reproduces bucket labels on **historical** dataset; table of frequencies. |
| **2** | **Threshold / risk table** | For each bucket: **AI threshold** and/or **risk multiplier** (static table v1—no online learning); implement read path in **host service** or **EA inputs** (your choice—prefer **host** if Phase 4 API exists). | Backtest or forward evidence: **at least one** bucket change shows intended effect vs global default. |
| **3** | **Release + cadence** | **Change log** per parameter change; **manual retrain** calendar (e.g. quarterly); rollback rule if metrics degrade. | Phase 5 **exit criteria** met: documented rules + evidence links (run ids / reports). |

---

## 8. Roadmap summary (milestones)

| Phase | Focus | Key output |
|-------|--------|------------|
| **1** | Deterministic CTS engine | **Done** — `CTS.mq5` + includes |
| **2** | Logging | CSV capture + **Docker Postgres** + schema/load scripts, `CTS_Log*` module, inputs, tester behavior |
| **3** | Offline ML | Python train/eval **from Postgres** (or CSV bootstrap), frozen features, **exported model** (ONNX or native, per §5.3) |
| **4** | Live inference (optional) | Local API + `CTS_AiGate`, shadow → filter |
| **5** | Adaptive (optional) | Threshold/risk by regime, manual retrain cycle |

**Suggested timeline (adjust to your cadence):**

- **Phase 2:** **§4.5** (five weekly blocks). Treat earlier **2a/2b** sprint language as optional shorthand—do not maintain two competing Phase 2 plans.
- **Phase 3:** **§5.5** (five core weeks + optional Week 6 regime / robustness).
- **Phase 4:** **§6.5** (four weekly blocks; optional—skip if you do not deploy live scoring).
- **Phase 5:** **§7.1** (three weekly blocks; only if adaptive controls add value after Phase 4).

---

## 9. Folder structure (practical, minimal)

Under `Experts/CTS/` (current) plus optional sibling repo for Python:

```
CTS/
├── CTS.mq5
├── Include/
│   ├── CTS_*.mqh          (existing)
│   ├── CTS_LogCsv.mqh     (Phase 2 — new)
│   └── CTS_AiGate.mqh     (Phase 4 — new)
├── concept.md
├── roadmap.md
└── AI_integration.md     (this file)

../cts_ml/                  (optional separate folder or git repo)
├── docker-compose.yml    # postgres (+ optional tools); bind to 127.0.0.1
├── README.md             # docker compose up, DSN, volume backup notes
├── requirements.txt      # psycopg, sqlalchemy (optional), pandas/polars, sklearn, xgboost OR lightgbm, uvicorn, fastapi (Phase 4)
├── scripts/
│   ├── build_dataset.py
│   ├── load_csv_to_postgres.py
│   ├── train_model.py
│   └── export_onnx_or_json.py
├── sql/
│   └── migrations/
│       └── 001_init_cts_logging.sql
├── notebooks/
├── configs/
│   ├── logging_schema_v1.yaml
│   └── .env.example          # POSTGRES_* for compose + POSTGRES_DSN for host Python—never commit real .env
└── app/                      # optional (Phase 4): FastAPI package—run with uvicorn on host by default
```

Avoid deeper nesting until a second EA or shared library forces it.

---

## 10. Traceability

| Topic | Document |
|--------|----------|
| Entry rules & bar alignment | `concept.md` |
| Phase 1 delivery checklist | `roadmap.md` |
| Long-term AI philosophy & stack ideas | `AI-Enhanced MT5 Trading System Architecture (1).md` |
| **Logging + AI phases for CTS** | **This file — `AI_integration.md`** |
| **Phase 2 week-by-week logging** | **This file — §4.5** |
| **Phase 2 v1 dataset contract (columns, time, CSV)** | **This file — §11** |
| **Docker vs host runtime** | **This file — §3.2** |


---

## 11. Phase 2 v1 dataset contract (frozen)

These decisions are the **dataset contract** between MT5, CSV loaders, PostgreSQL, and training code. **§11.1** fixes the earlier ambiguity between `UTC filenames` and `bar_time` semantics.

### 11.1 Time and bars (aligned)

| Field | Meaning | MQL5 |
|-------|---------|------|
| **`ts_gmt`** | Wall-clock when the row is **written**, in **UTC** | `TimeGMT()`; format as ISO-like UTC string when writing CSV |
| **`bar_time`** | **Broker/server** open time of the **signal candle** at shift **1** (the evaluated closed bar) | `iTime(symbol, timeframe, 1)` — this is **chart/broker time**, not forced to UTC unless your server uses UTC |
| **Candle close (offline)** | If needed for features | `bar_time + PeriodSeconds(timeframe)` in Python or documented helper |

**Rule:** do not assume `bar_time` equals UTC; document broker offset in `cts_ml/README.md` if you join to external UTC datasets.

### 11.2 Signal row frequency

One **signal evaluation** row per **new bar** on the configured signal timeframe (**not** per tick). Matches `CTS_IsNewBar` and closed-bar logic.

### 11.3 CSV files (signals)

- **Partition:** one file per **UTC calendar day** (from `TimeGMT()` for the filename only): `CTS_SIGNALS_YYYY-MM-DD.csv` under `MQL5/Files/<subdir>/` (default **`CTS_logs`** on chart; **`CTS_logs_tester`** in Strategy Tester when `InpLogInTester` — physical root is **`Tester/<id>/Agent-*/…`**, not `Terminal/<id>/…`; see `cts_ml/README.md`).
- **Encoding / delimiter:** **Comma**-separated. EA uses **`FILE_TXT` + `FILE_ANSI`** (ASCII-safe literals) for **broad terminal build compatibility**—`FILE_UTF8` is not available on all builds. Python: `read_csv(..., encoding="latin-1")` or ASCII-safe `utf-8` for v1 rows.
- **Append:** rolling append within the day; at UTC day rollover, open a new file and write the header if the file is new.

### 11.4 Frozen header (`schema_version = 1`)

Exact column order for `CTS_SIGNALS_*.csv` (row 1 = header):

`schema_version,ts_gmt,symbol,tf,bar_time,open1,high1,low1,close1,ema_fast_1,ema_slow_1,macd_main1,macd_sig1,atr1,spread_points,bias_long,bias_short,sig_long,sig_short,skip_reason,would_trade,signal_id`

**Phase 2 Week 1 (code):** writes this header (and optional Week-1 test row). **Week 2+** fills real signal rows.

**`CTS_EXECUTIONS_*.csv` (separate CSV `schema_version` in column 1):**

- **v1 (legacy):** `schema_version,ts_gmt,signal_id,symbol,tf,side,volume,sl,tp,retcode,deal_ticket,deal_time_gmt` with **`schema_version = 1`**.
- **v2 (EA ≥ 1.07):** insert **`entry_price`** after **`volume`**; first column **`schema_version = 2`**. Loader + `cts_orders.entry_price` (migration **`003_cts_orders_entry_price.sql`** on older DBs). Multi-year tester folders may mix v1 and v2 files after a recompile mid-backtest—both load.

### 11.5 `signal_id` (join key)

- **Primary key** linking signal → execution → outcome rows: a **string** generated in the EA when the signal row is produced (e.g. `SYMBOL_TF_YYYYMMDD_HHMMSS_msc`). Prefer deterministic, readable IDs over random UUID unless you add a proper RNG.
- **Composite** `(symbol, bar_time, magic)` remains useful for **debugging** and MT5 history alignment but is not the sole long-term join key.

### 11.6 Tester policy

- Default **logging in Strategy Tester** `InpLogInTester = false` to avoid huge disk use during optimization.
- When enabled: CSVs use **`InpLogTesterSubdir`** (default **`CTS_logs_tester`**), still under `MQL5/Files/…` but the **host root** is the tester agent folder, e.g. `%AppData%\MetaQuotes\Tester\<TERMINAL_ID>\Agent-127.0.0.1-3000\MQL5\Files\CTS_logs_tester\` (agent folder name varies by host/port).
- Optional: `InpLogTesterMaxRows` cap (signals + executions); **`0`** = no cap.

### 11.7 Machine / repo (Week 4+)

- **Docker Desktop** (Windows) for PostgreSQL; credentials in optional **`cts_ml/.env`** (gitignored), or Compose defaults for local dev — never in the EA or git.
- Suggested container name **`cts_postgres`**; default DB **`ctsdb`**; user **`cts_user`** (override with `POSTGRES_*` in `.env`).
- **Python 3.11+** for `cts_ml/scripts/` (Week 5+).
- **Layout:** this repo holds **`cts_ml/`** (Docker Compose, SQL migrations, future Python); the EA stays under `CTS.mq5` / `Include/`.

---

## 12. Revision history

| Version | Date | Notes |
|---------|------|--------|
| 1.0 | 2026-05-14 | Initial design: post–Phase 1 logging and AI infusion roadmap. |
| 1.1 | 2026-05-14 | Renamed document file to `AI_integration.md` (spelling: integration). |
| 1.2 | 2026-05-14 | Standardized datastore on **PostgreSQL**; EA remains CSV-first with Python bulk load; added `sql/migrations`, load script, ops notes. |
| 1.3 | 2026-05-14 | Added **§3.1** technology stack by phase; clarified sequential **CSV → Postgres** vs **Phase 4** inference; aligned exit criteria and `requirements.txt` hints. |
| 1.4 | 2026-05-14 | **Postgres in Docker**; **Python on host** by default; **§3.2** topology. |
| 1.5 | 2026-05-14 | **§4.5** Phase 2 weekly blocks; §8 points to §4.5. |
| 1.6 | 2026-05-14 | **§11** v1 dataset contract; Phase 2 **Week 1** `CTS_LogCsv` shell; `FILE_ANSI` portability fix. |
| 1.7 | 2026-05-14 | Phase 2 **Week 2**: real signal rows each new bar, OHLC in `CTSPriceBuf`, `CTS_SignalBias*`, UTC day rollover, `signal_id`. |
| 1.8 | 2026-05-14 | Phase 2 **Week 4**: `cts_ml/docker-compose.yml`, `.env.example`, `sql/migrations/001_init_cts_logging.sql` (`cts_signals`, `cts_orders`); README runbook; `.gitignore` for `.env`. |
| 1.9 | 2026-05-14 | Phase 2 **Week 5**: `scripts/load_csv_to_postgres.py`, `002_idempotent_load_indexes.sql`, `configs/.env.example`, `requirements.txt`; §4.4 exit criteria checked. |
| 1.10 | 2026-05-15 | **§5.5**, **§6.5**, **§7.1**: weekly implementation tables for Phases **3**, **4**, **5**; §8 timeline pointers updated. |
| 1.11 | 2026-05-15 | Phase 3 **Week 1**: `cts_ml/labeling.md`, `cts_ml/sql/examples/join_signals_orders_example.sql`, README Week-1 test notes; §5.5 Week 1 row paths updated. |
| 1.12 | 2026-05-15 | Document **Strategy Tester** CSV root (`MetaQuotes\Tester\…\Agent-*\MQL5\Files\`) vs **Terminal**; fix §11.6 path wording; loader examples in `cts_ml/README.md`. |
| 1.13 | 2026-05-15 | Phase 3 **Week 1 closed**: tester CSV load + join smoke; `labeling.md` §5.C locks **`y_has_fill`** on `would_trade`; verification log §8; example SQL uses verified `signal_id`. |
| 1.14 | 2026-05-15 | Phase 3 **Week 2**: `scripts/build_dataset.py`, `pandas`/`pyarrow` in `requirements.txt`, `cts_ml/data/` gitignored; README Week 2 runbook; §5.5 Week 2 row aligned. |
| 1.15 | 2026-05-15 | Phase 3 **Week 3**: `scripts/train_baseline.py`, `configs/baseline_split_v1.yaml`, `scikit-learn`/`PyYAML` in `requirements.txt`; README Week 3; §5.5 Week 3 row aligned. |
| 1.16 | 2026-05-15 | Phase 3 **Week 4**: `scripts/train_booster.py`, `scripts/ml_common.py` (shared split/features), `xgboost` in `requirements.txt`; calibration CSV + bucket JSON; README Week 4; §5.5 Week 4 row aligned. |
| 1.17 | 2026-05-15 | Phase 3 **Week 5**: `export_phase3_bundle.py`, `inference_score_row.py`, `exports/` gitignored; tighter pins + `joblib` in `requirements.txt`; README Week 5; §5.4 Phase 3 exit checked; §5.5 Week 5 row aligned. |
| 1.18 | 2026-05-15 | Phase 3 **Week 6 (optional)**: `regime_rules.py`, `augment_regime_column.py`, `train_regime_model.py`; README + labeling + §5.5 Week 6 row. |
| 1.19 | 2026-05-15 | **Execution CSV v2** + **`entry_price`**: `CTS_LogCsv.mqh` / `CTS.mq5` **v1.07**; `001` + **`003_cts_orders_entry_price.sql`**; `load_csv_to_postgres.py` (v1/v2 headers); `build_dataset.py` **`fill_entry_price`**; `labeling.md` §5.B; `cts_ml/README` + **§11.4** execution headers; **§4.5** Phase 2 Week 3 row + **§5.5** Phase 3 Weeks 1–2 rows. |
| 1.20 | 2026-05-15 | **`build_dataset.py`** dedupe join (EXISTS + LATERAL latest order); **`configs/.env`** workflow note in **`.env.example`**. |
| 1.21 | 2026-05-15 | **R / proxy labels** in **`build_dataset.py`** (fill SL/side/TP, **`forward_close_1`**, R prices, **`y_proxy_1bar_close_ge_plus_1r`**); **`labeling.md` §5.D**; **`train_baseline.py --out-model`**; **`export_phase3_bundle`** manifest optional columns; **§6.5.1** Phase 4 weekly checklist. |


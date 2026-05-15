# CTS ML / data (Phase 2)

Host-side **Python** (Week 5) and **PostgreSQL in Docker** (Week 4) support the pipeline in `AI_integration.md`: MT5 writes **CSV** under `MQL5/Files/<subdir>/` (path relative to the **active data sandbox**) → bulk load → Postgres for training.

## EA CSV output (v1.04)

| File pattern | When written |
|--------------|----------------|
| `CTS_SIGNALS_<YYYY-MM-DD>.csv` | `InpLogCsvEnable` and `InpLogSignals`; one row per new signal bar (UTC day in filename). |
| `CTS_EXECUTIONS_<YYYY-MM-DD>.csv` | Same master switch + `InpLogOrders`; one row after each **successful** market send (`deal_ticket`, `retcode`, GMT timestamps). |

### Time semantics (§11.1)

- **`ts_gmt` / `deal_time_gmt`:** UTC wall clock when the EA wrote the row (`TimeGMT()`), formatted as `YYYY-MM-DDTHH:MM:SSZ`.
- **`bar_time` (signals CSV):** string of **Unix seconds** for the **closed** signal bar open time (`iTime(sym, tf, 1)`), i.e. **broker/server** time — not necessarily UTC.
- **`signal_id`:** Join key between signal and execution rows: `symbol + "_" + tf + "_" + bar_time`.

### Strategy Tester

- Default: **`MQL_TESTER` without `InpLogInTester`** → no CSV file I/O.
- Enable tester logging: **`InpLogInTester = true`**. Files go under **`MQL5/Files/<InpLogTesterSubdir>/`** (default subdir `CTS_logs_tester`).
- **Windows path (tester):** CSVs are **not** under `MetaQuotes\Terminal\…\MQL5\Files\`. The Strategy Tester uses a per-agent sandbox, for example:

  `%AppData%\MetaQuotes\Tester\<TERMINAL_ID>\Agent-127.0.0.1-3000\MQL5\Files\CTS_logs_tester\CTS_SIGNALS_YYYY-MM-DD.csv`

  (same folder for `CTS_EXECUTIONS_*.csv`). The **`Agent-…`** folder name can differ (host/port); use **File → Open Data Folder** from the **tester** UI or search `CTS_logs_tester` under `%AppData%\MetaQuotes\Tester\<TERMINAL_ID>\`.

- **Live / visual chart:** files are under **`%AppData%\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Files\<InpLogCsvSubdir>\`** (default `CTS_logs`).

- **`InpLogTesterMaxRows`:** cap total CSV rows in tester; **`0`** = no cap.

---

## PostgreSQL (Week 4)

### Prerequisites

- **Docker Desktop** (Windows) or Docker Engine + Compose v2.

### Start the database

From **`cts_ml/`** (this folder):

1. Optional: `copy .env.example .env` and edit passwords (Compose also works with **built-in defaults** in `docker-compose.yml` if `.env` is absent).
2. Run:

```bash
docker compose up -d
```

- **Image:** `postgres:16.6-bookworm` (pinned).
- **Port:** `127.0.0.1:${POSTGRES_PORT:-5432}` → container `5432` (loopback only).
- **Volume:** named volume `cts_pgdata` for `PGDATA`.
- **First boot:** everything under **`sql/migrations/*.sql`** is mounted into **`docker-entrypoint-initdb.d/`** (lexical order). **`001_init_cts_logging.sql`** creates **`cts_signals`** / **`cts_orders`**; **`002_idempotent_load_indexes.sql`** adds **unique** indexes for idempotent CSV loads (`ON CONFLICT DO NOTHING`).

### Verify from the host

Defaults: user `cts_user`, database `ctsdb`, password `change_me_local_only` (override via `.env`).

**PowerShell:**

```powershell
docker compose exec -T postgres psql -U cts_user -d ctsdb -c "\dt"
docker compose exec -T postgres psql -U cts_user -d ctsdb -c "SELECT COUNT(*) FROM cts_signals;"
```

Adjust `-U` / `-d` if you changed `POSTGRES_USER` / `POSTGRES_DB`.

### Re-run DDL on an existing volume

`docker-entrypoint-initdb.d` runs **only on first empty data directory**. If you already created the volume without this migration, apply manually:

```powershell
Get-Content sql/migrations/001_init_cts_logging.sql -Raw | docker compose exec -T postgres psql -U cts_user -d ctsdb
Get-Content sql/migrations/002_idempotent_load_indexes.sql -Raw | docker compose exec -T postgres psql -U cts_user -d ctsdb
```

`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` are safe to re-run.

### Reset dev data (destructive)

```powershell
docker compose down -v
docker compose up -d
```

### Backup hint

```powershell
docker compose exec -T postgres pg_dump -U cts_user ctsdb > ctsdb_backup.sql
```

---

## CSV → Postgres loader (Week 5)

The EA is **unchanged** by this step: the loader is an **offline** host script.

### Setup

```powershell
cd cts_ml
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### DSN

- Copy **`../configs/.env.example`** to **`../configs/.env`** and set **`POSTGRES_DSN`**, or export the same variable in your shell.
- Default Compose credentials match the example DSN (`cts_user` / `ctsdb` / `change_me_local_only` on port **5432**).

### Load

Point **`--signals`** / **`--orders`** at globs under the correct **`MQL5/Files/<subdir>/`** root (see **Strategy Tester** above — tester runs often need the **`MetaQuotes\Tester\…\Agent-*\MQL5\Files\…`** path).

```powershell
# Live / visual (example)
python scripts/load_csv_to_postgres.py `
  --env-file ..\configs\.env `
  --signals "C:\Users\emili\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Files\CTS_logs\CTS_SIGNALS_*.csv" `
  --orders "C:\Users\emili\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\MQL5\Files\CTS_logs\CTS_EXECUTIONS_*.csv" `
  -v
```

```powershell
# Strategy Tester (example — adjust Agent-* folder to match your machine)
python scripts/load_csv_to_postgres.py `
  --env-file ..\configs\.env `
  --signals "C:\Users\emili\AppData\Roaming\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\CTS_logs_tester\CTS_SIGNALS_*.csv" `
  --orders "C:\Users\emili\AppData\Roaming\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\MQL5\Files\CTS_logs_tester\CTS_EXECUTIONS_*.csv" `
  -v
```

- **`--batch-size`** (default **500**): rows per multi-row `INSERT` (tune for large files; keep under Postgres parameter limits).
- **`--dry-run`**: parse CSV only, no database.
- **Idempotency:** requires migration **`002`** unique indexes. Re-loading the same CSV skips duplicates (`inserted` ≤ `read`).
- **`.csv.gz`**: supported for read paths ending in **`.gz`**.

### Confirm counts

```powershell
docker compose exec -T postgres psql -U cts_user -d ctsdb -c "SELECT COUNT(*) FROM cts_signals; SELECT COUNT(*) FROM cts_orders;"
```

---

## Phase 3 Week 1 (label + join spec)

| Artifact | Purpose |
|----------|---------|
| **`labeling.md`** | Join key, cardinality, time-field caveats, **v1 label options** (`has_fill` vs future +1R with `entry_price`). |
| **`sql/examples/join_signals_orders_example.sql`** | `cts_signals` **LEFT JOIN** `cts_orders` for one `signal_id` (edit the `params` CTE). |

**Quick test:** after CSV load, pick a `signal_id` (`SELECT signal_id FROM cts_signals ORDER BY ts_gmt DESC LIMIT 5;`), put it in the SQL file’s `params` CTE, then from **`cts_ml/`**:

```powershell
Get-Content sql/examples/join_signals_orders_example.sql -Raw | docker compose exec -T postgres psql -U cts_user -d ctsdb
```

Phase 3 Week 1 does **not** change the EA — compile/test MT5 as usual; DB/SQL steps validate the join spec.

---

## Phase 3 Week 2 (dataset build)

**Script:** `scripts/build_dataset.py` — reads **`cts_signals` ⟕ `cts_orders`** from Postgres, adds **`y_has_fill`**, default filter **`would_trade = true`** (see `labeling.md` §5.C). Writes **Parquet** (default) or **CSV** under **`data/`** (gitignored).

**Prereqs:** Docker Postgres up; CSVs loaded (`load_csv_to_postgres.py`); `pip install -r requirements.txt`.

```powershell
cd cts_ml
$env:POSTGRES_DSN="postgresql://cts_user:change_me_local_only@127.0.0.1:5432/ctsdb"  # or use configs\.env
python scripts/build_dataset.py --env-file ..\configs\.env -v --dry-run
python scripts/build_dataset.py --env-file ..\configs\.env -v
# optional: all signal rows (including would_trade=false)
python scripts/build_dataset.py --env-file ..\configs\.env --all-rows --format csv -o data\cts_dataset_all.csv
```

- **`--strict`:** exit non-zero if QC finds nulls, bad OHLC, duplicate `signal_id`, or wrong `schema_version`.
- **EA:** unchanged — **no compile** required for Week 2; validate with **dry-run** then inspect **`data/cts_dataset_<UTCdate>.parquet`**.

---

## Phase 3 Week 3 (walk-forward + sklearn baseline)

**Script:** `scripts/train_baseline.py` — reads **Week 2 Parquet**, sorts by **`ts_gmt`**, applies a **frozen index split** after sort (`configs/baseline_split_v1.yaml`, default **32** train rows / **14** val for the current 46-row `would_trade` slice — **re-tune** when `build_dataset` row counts change). Optional **`--purge-hours`** drops the start of validation until `ts_gmt > train_max + purge`.

**Models:** `--model rf` (default, small depth cap) or **`--model logistic`**. Reports **PR-AUC** (`average_precision`), **Brier**, **log_loss** on train and validation (train scores on tiny data are often optimistic).

```powershell
cd cts_ml
pip install -r requirements.txt
python scripts/train_baseline.py --dataset data\cts_dataset_test_run.parquet --model rf --out-metrics data\baseline_metrics.json
python scripts/train_baseline.py --dataset data\cts_dataset_test_run.parquet --auto-split 0.7 --write-split-config configs\baseline_split_v1.yaml
```

**EA:** unchanged — no MetaEditor compile for Week 3.

---

## Phase 3 Week 4 (XGBoost + calibration + buckets)

**Script:** `scripts/train_booster.py` — same **Parquet** and **`configs/baseline_split_v1.yaml`** as Week 3; trains a **reference RF** (same settings as `train_baseline.py`) and **XGBoost** with fixed modest hyperparameters + **`scale_pos_weight`**. Writes:

| Artifact | Purpose |
|----------|---------|
| **`*_metrics.json`** | Train/val metrics for RF + XGB, **`comparison`** (`xgb_beats_rf_on_validation_pr_auc`), **bucket** tables (`by_symbol`, **ATR quartiles** on validation). |
| **`*_calibration_val.csv`** | sklearn **`calibration_curve`** (uniform bins): mean predicted vs observed positive rate. |
| **`*_xgb.joblib`** | Full **`Pipeline`** (preprocess + XGB) for reload / Week 5 export path. |

```powershell
cd cts_ml
pip install -r requirements.txt
python scripts/train_booster.py --dataset data\cts_test_impl.parquet -v --out-prefix data\my_run
# default prefix: data/boost_<UTC> (three files per run)
```

**EA:** unchanged — no compile.

---

## Phase 3 Week 5 (export + inference handoff)

**Path:** **`exports/phase3_v1/`** (gitignored) — produced by **`scripts/export_phase3_bundle.py`** from a **`train_booster`** `*_xgb.joblib`. Contains **`model.joblib`** + **`manifest.json`** (feature column order, label spec, package versions). Optional copies of **`training_metrics.json`** and **`calibration_val.csv`**.

**Inference:** **`scripts/inference_score_row.py`** loads the bundle and prints **`proba_positive`** / **`score`** for one row from **`--row-json`** or **`--from-parquet`** + **`--row-index`**.

```powershell
cd cts_ml
python scripts/export_phase3_bundle.py --joblib data\_week4_test_run_xgb.joblib -v `
  --metrics-json data\_week4_test_run_metrics.json `
  --calibration-csv data\_week4_test_run_calibration_val.csv
python scripts/inference_score_row.py --bundle-dir exports\phase3_v1 --from-parquet data\cts_test_impl.parquet --row-index 0
```

**Format:** native **sklearn Pipeline + joblib** (not ONNX) per §5.3 single path.

**EA:** unchanged — no compile.

---

## Phase 3 Week 6 (optional — regime helper)

**Rule tag:** `scripts/regime_rules.py` — **`regime_rule_v1`** ∈ {`trend_long`, `trend_short`, `chop`} from logged EMA/MACD/bias only.

**Augment Parquet:** `scripts/augment_regime_column.py` — adds **`regime_rule_v1`** to a Week 2 dataset.

**Second model:** `scripts/train_regime_model.py` — multiclass **RandomForest** predicts **`regime_rule_v1`** using **numeric + `symbol`/`tf` only** (bias/sig excluded). Same **`configs/baseline_split_v1.yaml`** split as Week 3. Optional **`--out-model`** (joblib dict: `pipeline`, `label_encoder`, `regime_rule_version`).

```powershell
cd cts_ml
python scripts/augment_regime_column.py -i data\cts_test_impl.parquet -o data\cts_test_impl_regime.parquet
python scripts/train_regime_model.py --dataset data\cts_test_impl_regime.parquet -v --out-metrics data\regime_week6_metrics.json --out-model data\regime_rf_week6.joblib
```

**EA:** unchanged — no compile.

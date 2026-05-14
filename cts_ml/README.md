# CTS ML / data (Phase 2)

Host-side **Python** (Week 5) and **PostgreSQL in Docker** (Week 4) support the pipeline in `AI_integration.md`: MT5 writes **CSV** under `MQL5/Files/<subdir>/` → bulk load → Postgres for training.

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
- Enable tester logging: **`InpLogInTester = true`**. Files go under **`InpLogTesterSubdir`** (default `CTS_logs_tester`).
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

Point **`--signals`** / **`--orders`** at globs under your terminal’s **`MQL5/Files/<subdir>/`** (adjust the base path).

```powershell
python scripts/load_csv_to_postgres.py `
  --env-file ..\configs\.env `
  --signals "C:\Users\...\MQL5\Files\CTS_logs\CTS_SIGNALS_*.csv" `
  --orders "C:\Users\...\MQL5\Files\CTS_logs\CTS_EXECUTIONS_*.csv" `
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

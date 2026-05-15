#!/usr/bin/env python3
"""
Phase 3 Week 2 — build a training dataset from PostgreSQL (cts_signals ⟕ cts_orders).

Reads POSTGRES_DSN from the environment or from --env-file (configs/.env).
Default rows: would_trade = true and y_has_fill = EXISTS(order) per cts_ml/labeling.md §5.C.

Outputs Parquet (default) or CSV under cts_ml/data/ (gitignored). Does not touch the EA.
Join adds y_has_fill, fill-side/SL/TP from latest order, fill_entry_price, next-bar forward_close_1,
and derived R-price levels + optional y_proxy_1bar_close_ge_plus_1r (see labeling.md §5.D).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    import psycopg
except ImportError as e:
    print("Missing dependency. From cts_ml/: pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(1) from e

SCRIPT_DIR = Path(__file__).resolve().parent
CTS_ML_DIR = SCRIPT_DIR.parent
DATA_DIR = CTS_ML_DIR / "data"

SELECT_SQL_HEAD = """
SELECT
  s.schema_version,
  s.ts_gmt,
  s.symbol,
  s.tf,
  s.bar_time,
  s.open1,
  s.high1,
  s.low1,
  s.close1,
  s.ema_fast_1,
  s.ema_slow_1,
  s.macd_main1,
  s.macd_sig1,
  s.atr1,
  s.spread_points,
  s.bias_long,
  s.bias_short,
  s.sig_long,
  s.sig_short,
  s.skip_reason,
  s.would_trade,
  s.signal_id,
  EXISTS (SELECT 1 FROM cts_orders ox WHERE ox.signal_id = s.signal_id) AS y_has_fill,
  o.entry_price AS fill_entry_price,
  o.side AS fill_side,
  o.sl AS fill_sl,
  o.tp AS fill_tp,
  nxt.forward_close_1 AS forward_close_1
FROM cts_signals s
LEFT JOIN LATERAL (
  SELECT o2.entry_price, o2.side, o2.sl, o2.tp
  FROM cts_orders o2
  WHERE o2.signal_id = s.signal_id
  ORDER BY o2.ts_gmt DESC, o2.id DESC
  LIMIT 1
) o ON true
LEFT JOIN LATERAL (
  SELECT s2.close1 AS forward_close_1
  FROM cts_signals s2
  WHERE s2.symbol = s.symbol
    AND s2.tf = s.tf
    AND s2.bar_time > s.bar_time
  ORDER BY s2.bar_time ASC
  LIMIT 1
) nxt ON true
"""


def load_env_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


def build_sql(*, all_rows: bool) -> str:
    where = "" if all_rows else "WHERE s.would_trade = true\n"
    return SELECT_SQL_HEAD + where + "ORDER BY s.ts_gmt ASC, s.signal_id ASC\n"


def add_r_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """R geometry in price space (labeling.md §5.B); NaN when entry/sl/side missing or invalid."""
    out = df.copy()
    if "fill_entry_price" not in out.columns or "fill_sl" not in out.columns:
        return out
    ep = pd.to_numeric(out["fill_entry_price"], errors="coerce").to_numpy(dtype=float, copy=False)
    sl = pd.to_numeric(out["fill_sl"], errors="coerce").to_numpy(dtype=float, copy=False)
    side = out.get("fill_side", pd.Series("", index=out.index)).astype(str).str.upper().str.strip()
    buy = (side == "BUY").to_numpy()
    sell = (side == "SELL").to_numpy()
    n = len(out)
    r_arr = np.full(n, np.nan)
    if buy.any():
        r_arr[buy] = ep[buy] - sl[buy]
    if sell.any():
        r_arr[sell] = sl[sell] - ep[sell]
    r_arr[~buy & ~sell] = np.nan
    r_arr = np.where(np.isfinite(r_arr) & (r_arr > 0), r_arr, np.nan)
    r = pd.Series(r_arr, index=out.index)

    p_arr = np.full(n, np.nan)
    m_arr = np.full(n, np.nan)
    ok = np.isfinite(r_arr) & (r_arr > 0)
    p_arr[ok & buy] = ep[ok & buy] + r_arr[ok & buy]
    p_arr[ok & sell] = ep[ok & sell] - r_arr[ok & sell]
    m_arr[ok & buy] = ep[ok & buy] - r_arr[ok & buy]
    m_arr[ok & sell] = ep[ok & sell] + r_arr[ok & sell]

    out["initial_r_price"] = r
    out["plus_1r_price"] = p_arr
    out["minus_1r_price"] = m_arr

    fc = pd.to_numeric(out.get("forward_close_1"), errors="coerce").to_numpy(dtype=float, copy=False)
    yp = np.full(n, np.nan)
    vplus = np.isfinite(fc) & np.isfinite(p_arr) & ok
    yp[vplus & buy] = (fc[vplus & buy] >= p_arr[vplus & buy]).astype(float)
    yp[vplus & sell] = (fc[vplus & sell] <= p_arr[vplus & sell]).astype(float)
    out["y_proxy_1bar_close_ge_plus_1r"] = yp
    return out


def fetch_counts(conn: psycopg.Connection) -> tuple[int, int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM cts_signals")
        n_sig = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM cts_orders")
        n_ord = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM cts_signals WHERE would_trade = true")
        n_trade = int(cur.fetchone()[0])
    return n_sig, n_ord, n_trade


def run_qc(df: pd.DataFrame, *, verbose: bool) -> list[str]:
    """Return human-readable QC issues (non-fatal unless --strict)."""
    issues: list[str] = []
    if df.empty:
        issues.append("dataset is empty after query")
        return issues

    allow_na = {
        "fill_entry_price",
        "fill_side",
        "fill_sl",
        "fill_tp",
        "forward_close_1",
        "initial_r_price",
        "plus_1r_price",
        "minus_1r_price",
        "y_proxy_1bar_close_ge_plus_1r",
    }  # order join / legacy entry_price / last bar has no next row / invalid R
    null_cols = [c for c in df.columns if c not in allow_na and df[c].isna().any()]
    if null_cols:
        issues.append(f"null values in columns: {null_cols}")

    if "fill_entry_price" in df.columns and "y_has_fill" in df.columns:
        n_legacy = int((df["y_has_fill"] & df["fill_entry_price"].isna()).sum())
        if n_legacy:
            # Not a strict failure: common for 7y backtests logged before execution CSV v2.
            print(
                f"QC info: y_has_fill with null fill_entry_price: {n_legacy} rows "
                "(CTS_EXECUTIONS schema v1 / DB without entry_price)",
                file=sys.stderr,
            )

    for c in ("open1", "high1", "low1", "close1", "atr1", "spread_points"):
        if c in df.columns and (df[c] < 0).any():
            issues.append(f"negative values in {c}: count={(df[c] < 0).sum()}")

    bad_ohlc = (
        (df["high1"] < df["low1"])
        | (df["high1"] < df["open1"])
        | (df["high1"] < df["close1"])
        | (df["low1"] > df["open1"])
        | (df["low1"] > df["close1"])
    )
    n_bad = int(bad_ohlc.sum())
    if n_bad:
        issues.append(f"OHLC inconsistency rows: {n_bad}")

    if (df["schema_version"] != 1).any():
        issues.append("non-1 schema_version rows present")

    pos = (df["y_has_fill"]).sum()
    neg = (~df["y_has_fill"]).sum()
    if verbose:
        print(f"QC: y_has_fill True={int(pos)} False={int(neg)}", file=sys.stderr)

    dup = df["signal_id"].duplicated().sum()
    if dup:
        issues.append(f"duplicate signal_id rows: {int(dup)}")

    return issues


def default_out_path(*, fmt: str) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ext = "parquet" if fmt == "parquet" else "csv"
    return DATA_DIR / f"cts_dataset_{day}.{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build CTS ML dataset from Postgres.")
    ap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Dotenv file (e.g. ../configs/.env) to load POSTGRES_DSN",
    )
    ap.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output file (.parquet or .csv). Default: cts_ml/data/cts_dataset_<UTCdate>.parquet",
    )
    ap.add_argument(
        "--format",
        choices=("parquet", "csv"),
        default="parquet",
        help="Output format (default: parquet)",
    )
    ap.add_argument(
        "--all-rows",
        action="store_true",
        help="Include would_trade=false rows (default: only would_trade=true per labeling.md)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + QC + print counts; do not write file",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if QC finds issues",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.env_file is not None:
        if not args.env_file.is_file():
            print(f"env file not found: {args.env_file}", file=sys.stderr)
            return 1
        load_env_file(args.env_file)

    dsn = os.environ.get("POSTGRES_DSN", "").strip()
    if not dsn:
        print("POSTGRES_DSN is not set (use --env-file or export).", file=sys.stderr)
        return 1

    sql = build_sql(all_rows=args.all_rows)
    if args.verbose:
        print(sql[:400] + "...", file=sys.stderr)

    with psycopg.connect(dsn) as conn:
        n_sig, n_ord, n_trade = fetch_counts(conn)
        if args.verbose:
            print(
                f"DB: cts_signals={n_sig} cts_orders={n_ord} would_trade_true={n_trade}",
                file=sys.stderr,
            )
        with conn.cursor() as cur:
            cur.execute(sql)
            colnames = [d[0] for d in cur.description]
            rows = cur.fetchall()
        df = pd.DataFrame.from_records(rows, columns=colnames)

    df = add_r_price_columns(df)

    issues = run_qc(df, verbose=args.verbose)
    for msg in issues:
        print(f"QC warning: {msg}", file=sys.stderr)

    print(
        f"Rows pulled: {len(df)} (all_rows={args.all_rows}); "
        f"source cts_signals={n_sig} would_trade_true={n_trade}"
    )

    if args.strict and issues:
        return 2

    if args.dry_run:
        print("Dry run: no file written.")
        return 0

    out = args.output or default_out_path(fmt=args.format)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "parquet":
        df.to_parquet(out, index=False)
    else:
        df.to_csv(out, index=False)

    print(f"Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

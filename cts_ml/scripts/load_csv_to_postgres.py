#!/usr/bin/env python3
"""
Bulk-load CTS EA CSV logs into PostgreSQL (AI_integration.md Phase 2 Week 5).

Expects tables cts_signals / cts_orders from sql/migrations/001 + unique indexes
from 002_idempotent_load_indexes.sql (ON CONFLICT DO NOTHING).

Does not run inside MT5; safe to run while the terminal is closed. EA tick path is unchanged.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import os
import sys
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
except ImportError:
    print("Missing psycopg. From cts_ml/: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)

EXPECTED_SCHEMA = 1

SIGNAL_COLS = (
    "schema_version",
    "ts_gmt",
    "symbol",
    "tf",
    "bar_time",
    "open1",
    "high1",
    "low1",
    "close1",
    "ema_fast_1",
    "ema_slow_1",
    "macd_main1",
    "macd_sig1",
    "atr1",
    "spread_points",
    "bias_long",
    "bias_short",
    "sig_long",
    "sig_short",
    "skip_reason",
    "would_trade",
    "signal_id",
)

ORDER_COLS = (
    "schema_version",
    "ts_gmt",
    "signal_id",
    "symbol",
    "tf",
    "side",
    "volume",
    "sl",
    "tp",
    "retcode",
    "deal_ticket",
    "deal_time_gmt",
)


def load_env_file(path: Path) -> None:
    """Apply KEY=value lines into os.environ (later lines override earlier)."""
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


def parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "t", "yes")


def parse_ts_gmt(raw: str) -> datetime:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def open_text(path: Path):
    name = path.name.lower()
    if name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", newline="", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace", newline="")


def _norm_header(h: str) -> str:
    return h.strip().lstrip("\ufeff")


def iter_signal_tuples(
    path: Path, verbose: bool
) -> Iterator[tuple[Any, ...] | None]:
    with open_text(path) as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return
        fn = [_norm_header(h) for h in reader.fieldnames]
        if tuple(fn) != SIGNAL_COLS:
            raise ValueError(
                f"{path}: unexpected header {fn!r}; expected {SIGNAL_COLS!r}"
            )
        for i, row in enumerate(reader, start=2):
            try:
                sv = int(row["schema_version"])
                if sv != EXPECTED_SCHEMA:
                    if verbose:
                        print(f"{path}:{i}: skip schema_version={sv}", file=sys.stderr)
                    continue
                tup = (
                    sv,
                    parse_ts_gmt(row["ts_gmt"]),
                    row["symbol"].strip(),
                    row["tf"].strip(),
                    int(row["bar_time"]),
                    float(row["open1"]),
                    float(row["high1"]),
                    float(row["low1"]),
                    float(row["close1"]),
                    float(row["ema_fast_1"]),
                    float(row["ema_slow_1"]),
                    float(row["macd_main1"]),
                    float(row["macd_sig1"]),
                    float(row["atr1"]),
                    float(row["spread_points"]),
                    parse_bool(row["bias_long"]),
                    parse_bool(row["bias_short"]),
                    parse_bool(row["sig_long"]),
                    parse_bool(row["sig_short"]),
                    row.get("skip_reason", "") or "",
                    parse_bool(row["would_trade"]),
                    row["signal_id"].strip(),
                )
                yield tup
            except (KeyError, ValueError, TypeError) as e:
                print(f"{path}:{i}: skip bad row: {e}", file=sys.stderr)
                yield None


def iter_order_tuples(path: Path, verbose: bool) -> Iterator[tuple[Any, ...] | None]:
    with open_text(path) as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return
        fn = [_norm_header(h) for h in reader.fieldnames]
        if tuple(fn) != ORDER_COLS:
            raise ValueError(
                f"{path}: unexpected header {fn!r}; expected {ORDER_COLS!r}"
            )
        for i, row in enumerate(reader, start=2):
            try:
                sv = int(row["schema_version"])
                if sv != EXPECTED_SCHEMA:
                    if verbose:
                        print(f"{path}:{i}: skip schema_version={sv}", file=sys.stderr)
                    continue
                deal = int(row["deal_ticket"])
                tup = (
                    sv,
                    parse_ts_gmt(row["ts_gmt"]),
                    row["signal_id"].strip(),
                    row["symbol"].strip(),
                    row["tf"].strip(),
                    row["side"].strip(),
                    float(row["volume"]),
                    float(row["sl"]),
                    float(row["tp"]),
                    int(row["retcode"]),
                    deal,
                    parse_ts_gmt(row["deal_time_gmt"]),
                )
                yield tup
            except (KeyError, ValueError, TypeError) as e:
                print(f"{path}:{i}: skip bad row: {e}", file=sys.stderr)
                yield None


def chunked(it: Iterator[tuple[Any, ...]], n: int) -> Iterator[list[tuple[Any, ...]]]:
    batch: list[tuple[Any, ...]] = []
    for item in it:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


def insert_signals_batch(cur, batch: Sequence[tuple[Any, ...]]) -> int:
    if not batch:
        return 0
    w = len(SIGNAL_COLS)
    row_ph = "(" + ",".join(["%s"] * w) + ")"
    all_ph = ",".join([row_ph] * len(batch))
    flat: list[Any] = [v for row in batch for v in row]
    sql = f"""
        INSERT INTO cts_signals ({",".join(SIGNAL_COLS)})
        VALUES {all_ph}
        ON CONFLICT (signal_id) DO NOTHING
    """
    cur.execute(sql, flat)
    return cur.rowcount


def insert_orders_batch(cur, batch: Sequence[tuple[Any, ...]]) -> int:
    if not batch:
        return 0
    w = len(ORDER_COLS)
    row_ph = "(" + ",".join(["%s"] * w) + ")"
    all_ph = ",".join([row_ph] * len(batch))
    flat: list[Any] = [v for row in batch for v in row]
    sql = f"""
        INSERT INTO cts_orders ({",".join(ORDER_COLS)})
        VALUES {all_ph}
        ON CONFLICT (deal_ticket) DO NOTHING
    """
    cur.execute(sql, flat)
    return cur.rowcount


def expand_paths(patterns: Sequence[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        matches = sorted(glob.glob(pat, recursive=True))
        if not matches:
            print(f"Warning: pattern matched no files: {pat!r}", file=sys.stderr)
        for m in matches:
            out.append(Path(m))
    # stable unique
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def load_signals(
    conn: psycopg.Connection,
    paths: Sequence[Path],
    batch_size: int,
    verbose: bool,
) -> tuple[int, int]:
    """Returns (rows_read, rows_inserted)."""
    read_n = 0
    ins_n = 0
    for path in paths:
        def tuples_for_file() -> Iterator[tuple[Any, ...]]:
            for t in iter_signal_tuples(path, verbose):
                if t is not None:
                    yield t

        batches = list(chunked(tuples_for_file(), batch_size))
        read_n += sum(len(b) for b in batches)
        file_ins = 0
        with conn.cursor() as cur:
            for b in batches:
                file_ins += insert_signals_batch(cur, b)
        ins_n += file_ins
        if verbose:
            print(f"signals {path}: batches={len(batches)} inserted={file_ins}")
    return read_n, ins_n


def load_orders(
    conn: psycopg.Connection,
    paths: Sequence[Path],
    batch_size: int,
    verbose: bool,
) -> tuple[int, int]:
    read_n = 0
    ins_n = 0
    for path in paths:
        def tuples_for_file() -> Iterator[tuple[Any, ...]]:
            for t in iter_order_tuples(path, verbose):
                if t is not None:
                    yield t

        batches = list(chunked(tuples_for_file(), batch_size))
        read_n += sum(len(b) for b in batches)
        file_ins = 0
        with conn.cursor() as cur:
            for b in batches:
                file_ins += insert_orders_batch(cur, b)
        ins_n += file_ins
        if verbose:
            print(f"orders {path}: batches={len(batches)} inserted={file_ins}")
    return read_n, ins_n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Load CTS_SIGNALS_*.csv / CTS_EXECUTIONS_*.csv into PostgreSQL."
    )
    ap.add_argument(
        "--dsn",
        default=os.environ.get("POSTGRES_DSN", ""),
        help="postgresql://... (default: env POSTGRES_DSN)",
    )
    ap.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional KEY=value file (e.g. configs/.env) applied before reading POSTGRES_DSN",
    )
    ap.add_argument(
        "--signals",
        nargs="*",
        default=[],
        metavar="GLOB",
        help="Glob(s) for CTS_SIGNALS_*.csv",
    )
    ap.add_argument(
        "--orders",
        nargs="*",
        default=[],
        metavar="GLOB",
        help="Glob(s) for CTS_EXECUTIONS_*.csv",
    )
    ap.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per INSERT statement (default 500)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse CSV only; do not connect or write",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.env_file is not None:
        if not args.env_file.is_file():
            print(f"Env file not found: {args.env_file}", file=sys.stderr)
            return 2
        load_env_file(args.env_file)
    args.dsn = args.dsn or os.environ.get("POSTGRES_DSN", "")

    sig_paths = expand_paths(args.signals)
    ord_paths = expand_paths(args.orders)
    if not sig_paths and not ord_paths:
        print("Provide --signals and/or --orders globs.", file=sys.stderr)
        return 2

    if args.batch_size < 1:
        print("--batch-size must be >= 1", file=sys.stderr)
        return 2

    if args.dry_run:
        read_s = read_o = 0
        for p in sig_paths:
            read_s += sum(1 for _ in iter_signal_tuples(p, args.verbose) if _ is not None)
        for p in ord_paths:
            read_o += sum(1 for _ in iter_order_tuples(p, args.verbose) if _ is not None)
        print(f"[dry-run] parsed signal rows: {read_s}, order rows: {read_o}")
        return 0

    if not args.dsn:
        print("Set POSTGRES_DSN or pass --dsn (postgresql://user:pass@127.0.0.1:5432/db)", file=sys.stderr)
        return 2

    read_s = ins_s = read_o = ins_o = 0
    try:
        with psycopg.connect(args.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            if sig_paths:
                read_s, ins_s = load_signals(
                    conn, sig_paths, args.batch_size, args.verbose
                )
            if ord_paths:
                read_o, ins_o = load_orders(
                    conn, ord_paths, args.batch_size, args.verbose
                )
    except psycopg.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        return 1

    print(
        f"Done. signals read={read_s} inserted={ins_s}; "
        f"orders read={read_o} inserted={ins_o} (skipped = duplicates / conflicts)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

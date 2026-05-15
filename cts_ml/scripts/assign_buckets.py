#!/usr/bin/env python3
"""
Phase 5 Week 1 — assign adaptive buckets on a Phase 3 Parquet dataset.

- Fits ATR quartile edges on the train slice only (split YAML).
- Adds regime_rule_v1, atr_quartile, bucket_id.
- Prints frequency tables for train / val.

Does not touch the EA.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402
from adaptive_buckets import (  # noqa: E402
    CTS_ML_DIR,
    DEFAULT_ADAPTIVE,
    augment_buckets,
    fit_atr_edges,
    load_adaptive_config,
    save_adaptive_config,
    summarize_frequencies,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="CTS Phase 5 Week 1 — bucket assignment.")
    ap.add_argument("--dataset", "-i", type=Path, default=None, help="Parquet (default: newest cts_dataset_*.parquet)")
    ap.add_argument("--config", type=Path, default=DEFAULT_ADAPTIVE, help="adaptive_v1.yaml")
    ap.add_argument("--split-config", type=Path, default=None, help="Override split YAML (default: from adaptive config)")
    ap.add_argument("--output", "-o", type=Path, default=None, help="Write Parquet with bucket columns")
    ap.add_argument("--freq-csv", type=Path, default=None, help="Write frequency summary CSV")
    ap.add_argument("--write-cutpoints", action="store_true", help="Update config atr_quartile.edges from train fit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cfg = load_adaptive_config(args.config)
    split_path = args.split_config
    if split_path is None:
        rel = cfg.get("split_config", "configs/baseline_split_v1.yaml")
        split_path = Path(rel) if Path(rel).is_absolute() else CTS_ML_DIR / rel
    if not split_path.is_file():
        print(f"split config not found: {split_path}", file=sys.stderr)
        return 1

    ds_path = args.dataset or mlc.latest_parquet()
    if not ds_path.is_file():
        print(f"dataset not found: {ds_path}", file=sys.stderr)
        return 1

    split_cfg = mlc.load_split_config(split_path)
    df = pd.read_parquet(ds_path)
    if "ts_gmt" not in df.columns:
        print("dataset missing ts_gmt", file=sys.stderr)
        return 1
    if "atr1" not in df.columns:
        print("dataset missing atr1", file=sys.stderr)
        return 1

    df = df.sort_values("ts_gmt", kind="mergesort").reset_index(drop=True)
    train_df, val_df, split_meta = mlc.temporal_split_by_index(
        df,
        train_row_end_exclusive=int(split_cfg["train_row_end_exclusive"]),
        purge_hours=int(split_cfg.get("purge_hours", 0)),
    )

    edges = fit_atr_edges(train_df["atr1"])
    if args.verbose:
        print(f"Train/val rows: {split_meta['train_rows']} / {split_meta['val_rows']}")
        print(f"ATR edges (train quantiles): {edges}")

    full_aug, _ = augment_buckets(df, cfg, edges=edges)
    train_aug = full_aug.iloc[: len(train_df)].copy()
    val_aug = full_aug.iloc[len(train_df) :].copy()

    bucket_mode = str(cfg.get("bucket_mode", "combined"))
    freq = summarize_frequencies(train_aug, val_aug, bucket_mode=bucket_mode)
    print(freq.to_string(index=False))

    if args.freq_csv:
        args.freq_csv.parent.mkdir(parents=True, exist_ok=True)
        freq.to_csv(args.freq_csv, index=False)
        print(f"Wrote {args.freq_csv}")

    if args.write_cutpoints:
        cfg["atr_quartile"]["edges"] = edges
        save_adaptive_config(args.config, cfg)
        print(f"Updated {args.config} with atr_quartile.edges")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        full_aug.to_parquet(args.output, index=False)
        print(f"Wrote {args.output} ({len(full_aug)} rows)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

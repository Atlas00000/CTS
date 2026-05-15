#!/usr/bin/env python3
"""
Phase 5 Week 2 — per-bucket evidence tables and suggested AI thresholds.

Reads Parquet with bucket_id (from assign_buckets.py). Optionally writes policies
into configs/adaptive_v1.yaml (--write-policies).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402
from adaptive_buckets import CTS_ML_DIR, DEFAULT_ADAPTIVE, load_adaptive_config, save_adaptive_config  # noqa: E402

DEFAULT_THRESHOLD = 0.65
MIN_BUCKET_ROWS = 5


def _rate(series: pd.Series) -> float | None:
    if series is None or len(series) == 0:
        return None
    s = series.dropna()
    if len(s) == 0:
        return None
    return float(s.mean())


def bucket_stats_frame(df: pd.DataFrame, split: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for bucket_id, grp in df.groupby("bucket_id", observed=True):
        row: dict[str, Any] = {
            "split": split,
            "bucket_id": str(bucket_id),
            "n": int(len(grp)),
        }
        if "y_has_fill" in grp.columns:
            row["fill_rate"] = _rate(grp["y_has_fill"].astype(float))
        if "y_proxy_1bar_close_ge_plus_1r" in grp.columns:
            row["proxy_plus_1r_rate"] = _rate(grp["y_proxy_1bar_close_ge_plus_1r"].astype(float))
        rows.append(row)
    out = pd.DataFrame(rows)
    if len(out):
        out = out.sort_values(["split", "bucket_id"]).reset_index(drop=True)
    return out


def suggest_threshold(fill_rate: float | None, n: int, default: float = DEFAULT_THRESHOLD) -> float:
    """Static v1 rule: higher historical fill → slightly lower threshold (allow more)."""
    if n < MIN_BUCKET_ROWS or fill_rate is None:
        return default
    if fill_rate >= 0.78:
        return 0.60
    if fill_rate >= 0.72:
        return 0.63
    if fill_rate >= 0.68:
        return default
    if fill_rate >= 0.62:
        return 0.68
    return 0.72


def build_policies(
    train_stats: pd.DataFrame,
    *,
    default_threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    by_bucket: dict[str, dict[str, float]] = {}
    for _, r in train_stats.iterrows():
        bid = str(r["bucket_id"])
        n = int(r["n"])
        fill = r.get("fill_rate")
        fill_f = float(fill) if fill is not None and pd.notna(fill) else None
        thr = suggest_threshold(fill_f, n, default_threshold)
        risk = 1.0
        if fill_f is not None and fill_f < 0.62:
            risk = 0.85
        by_bucket[bid] = {"threshold": round(thr, 2), "risk_multiplier": risk}

    return {
        "default": {"threshold": default_threshold, "risk_multiplier": 1.0},
        "by_bucket": by_bucket,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="CTS Phase 5 Week 2 — bucket evidence + policies.")
    ap.add_argument("--dataset", "-i", type=Path, default=None, help="Parquet with bucket_id")
    ap.add_argument("--config", type=Path, default=DEFAULT_ADAPTIVE)
    ap.add_argument("--split-config", type=Path, default=None)
    ap.add_argument("--out-stats", type=Path, default=CTS_ML_DIR / "data" / "adaptive_v1_bucket_stats.csv")
    ap.add_argument("--out-json", type=Path, default=CTS_ML_DIR / "data" / "adaptive_v1_policy_suggest.json")
    ap.add_argument("--write-policies", action="store_true", help="Merge policies into adaptive_v1.yaml")
    ap.add_argument("--default-threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cfg = load_adaptive_config(args.config)
    split_path = args.split_config
    if split_path is None:
        rel = cfg.get("split_config", "configs/baseline_split_v1.yaml")
        split_path = Path(rel) if Path(rel).is_absolute() else CTS_ML_DIR / rel

    ds_path = args.dataset or (CTS_ML_DIR / "data" / "cts_dataset_adaptive_v1.parquet")
    if not ds_path.is_file():
        ds_path = mlc.latest_parquet()
    if not ds_path.is_file():
        print(f"dataset not found: {ds_path}", file=sys.stderr)
        return 1
    if "bucket_id" not in pd.read_parquet(ds_path, columns=["bucket_id"]).columns:
        print("dataset missing bucket_id — run assign_buckets.py first", file=sys.stderr)
        return 1

    split_cfg = mlc.load_split_config(split_path)
    df = pd.read_parquet(ds_path).sort_values("ts_gmt", kind="mergesort").reset_index(drop=True)
    train_df, val_df, meta = mlc.temporal_split_by_index(
        df,
        train_row_end_exclusive=int(split_cfg["train_row_end_exclusive"]),
        purge_hours=int(split_cfg.get("purge_hours", 0)),
    )

    stats = pd.concat(
        [bucket_stats_frame(train_df, "train"), bucket_stats_frame(val_df, "val")],
        ignore_index=True,
    )
    print(stats.to_string(index=False))

    train_only = stats[stats["split"] == "train"].copy()
    policies = build_policies(train_only, default_threshold=args.default_threshold)

    if args.out_stats:
        args.out_stats.parent.mkdir(parents=True, exist_ok=True)
        stats.to_csv(args.out_stats, index=False)
        print(f"Wrote {args.out_stats}")

    if args.out_json:
        payload = {
            "train_val_meta": meta,
            "policies_suggested": policies,
            "distinct_thresholds": sorted({p["threshold"] for p in policies["by_bucket"].values()}),
        }
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote {args.out_json}")

    if args.write_policies:
        cfg["policies"] = policies
        cfg["policy_notes"] = (
            "Week2: threshold from train fill_rate tiers; risk_multiplier=0.85 when fill_rate<0.62; "
            "sparse buckets (<5 rows) use default threshold."
        )
        save_adaptive_config(args.config, cfg)
        print(f"Updated {args.config} policies.by_bucket ({len(policies['by_bucket'])} entries)")

    if args.verbose:
        print("Suggested thresholds:", policies["by_bucket"])

  # Week 2 exit: at least one bucket differs from default
    diffs = [b for b, p in policies["by_bucket"].items() if p["threshold"] != args.default_threshold]
    if not diffs:
        print("WARN: no bucket threshold differs from default", file=sys.stderr)
    else:
        print(f"Buckets with non-default threshold: {len(diffs)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

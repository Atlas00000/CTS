#!/usr/bin/env python3
"""Phase 5 Week 6 (stretch) — UTC hour session bins on Parquet (analysis only).

Not wired to API/EA in v1. Use to explore session effects before promoting to YAML.

  cd cts_ml
  python scripts/session_buckets.py -i data/cts_dataset_adaptive_v1.parquet -v
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

CTS_ML = Path(__file__).resolve().parent.parent

# London-ish / NY-ish / off-hours (UTC hour of bar_time)
SESSION_LABELS = ("asia", "london", "ny", "off")


def hour_utc_from_bar_time(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series, unit="s", utc=True, errors="coerce")
    return ts.dt.hour


def assign_session_hour(hour: pd.Series) -> pd.Series:
    """Simple v1 bins (UTC hour)."""

    def _one(h: int) -> str:
        if 7 <= h < 12:
            return "london"
        if 12 <= h < 21:
            return "ny"
        if 0 <= h < 7:
            return "asia"
        return "off"

    return hour.map(lambda x: _one(int(x)) if pd.notna(x) else "off")


def main() -> int:
    ap = argparse.ArgumentParser(description="Assign session_hour_v1 on Parquet (Week 6 stretch).")
    ap.add_argument("-i", "--dataset", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, default=None, help="Optional output parquet")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    df = pd.read_parquet(args.dataset)
    if "bar_time" not in df.columns:
        raise SystemExit("dataset missing bar_time")

    h = hour_utc_from_bar_time(df["bar_time"])
    df = df.copy()
    df["session_hour_v1"] = assign_session_hour(h)

    vc = df["session_hour_v1"].value_counts()
    if args.verbose:
        print(vc.to_string())
        if "y_has_fill" in df.columns:
            print("\nfill_rate by session:")
            print(df.groupby("session_hour_v1")["y_has_fill"].mean().round(4).to_string())

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(args.out, index=False)
        print(f"Wrote {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

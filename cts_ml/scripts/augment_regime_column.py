#!/usr/bin/env python3
"""
Phase 3 Week 6 — append `regime_rule_v1` column to a build_dataset Parquet (rule in regime_rules.py).

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

from regime_rules import apply_regime_rule_v1  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Add regime_rule_v1 to Parquet.")
    ap.add_argument("--input", "-i", type=Path, required=True)
    ap.add_argument("--output", "-o", type=Path, required=True)
    ap.add_argument("--format", choices=("parquet", "csv"), default="parquet")
    args = ap.parse_args()

    if not args.input.is_file():
        print(f"not found: {args.input}", file=sys.stderr)
        return 1

    df = pd.read_parquet(args.input) if args.input.suffix.lower() == ".parquet" else pd.read_csv(args.input)
    if "ts_gmt" in df.columns:
        df = df.sort_values("ts_gmt", kind="mergesort").reset_index(drop=True)
    df["regime_rule_v1"] = apply_regime_rule_v1(df)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "parquet":
        df.to_parquet(args.output, index=False)
    else:
        df.to_csv(args.output, index=False)
    counts = df["regime_rule_v1"].value_counts().to_dict()
    print(f"Wrote {args.output}; regime_rule_v1 counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

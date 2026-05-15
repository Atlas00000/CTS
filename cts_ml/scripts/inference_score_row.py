#!/usr/bin/env python3
"""
Phase 3 Week 5 — score a single feature row with an exported bundle (model.joblib + manifest.json).

Input row must match manifest feature_columns (no ts_gmt / signal_id required for scoring).

Does not touch the EA.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
CTS_ML_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402


def load_manifest(bundle_dir: Path) -> dict:
    p = bundle_dir / "manifest.json"
    if not p.is_file():
        raise FileNotFoundError(f"missing manifest.json in {bundle_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def row_from_json(obj: dict, manifest: dict) -> pd.DataFrame:
    cols = manifest["feature_columns"]
    miss = [c for c in cols if c not in obj]
    if miss:
        raise ValueError(f"row JSON missing keys: {miss}")
    row = {c: obj[c] for c in cols}
    df = pd.DataFrame([row])
    for c in manifest["boolean_columns"]:
        df[c] = df[c].astype(bool).astype(np.int8)
    for c in manifest["categorical_columns"]:
        df[c] = df[c].astype(str)
    for c in manifest["numeric_columns"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def row_from_parquet(path: Path, index: int, manifest: dict) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if index < 0 or index >= len(df):
        raise IndexError(f"parquet row index {index} out of range (n={len(df)})")
    row = df.iloc[[index]]
    cols = manifest["feature_columns"]
    miss = [c for c in cols if c not in row.columns]
    if miss:
        raise ValueError(f"parquet missing columns: {miss}")
    out = row[cols].copy()
    for c in manifest["boolean_columns"]:
        out[c] = out[c].astype(bool).astype(np.int8)
    for c in manifest["categorical_columns"]:
        out[c] = out[c].astype(str)
    for c in manifest["numeric_columns"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Score one row with exported Phase 3 bundle.")
    ap.add_argument(
        "--bundle-dir",
        type=Path,
        default=CTS_ML_DIR / "exports" / "phase3_v1",
        help="Directory with model.joblib + manifest.json",
    )
    ap.add_argument("--row-json", type=Path, default=None, help="JSON object with feature keys (file)")
    ap.add_argument(
        "--from-parquet",
        type=Path,
        default=None,
        help="Use row at --row-index from build_dataset Parquet",
    )
    ap.add_argument("--row-index", type=int, default=0)
    args = ap.parse_args()

    bundle = args.bundle_dir
    model_p = bundle / "model.joblib"
    if not model_p.is_file():
        print(f"model.joblib not found under {bundle}", file=sys.stderr)
        return 1

    manifest = load_manifest(bundle)
    clf = joblib.load(model_p)

    if args.from_parquet is not None:
        X = row_from_parquet(args.from_parquet, args.row_index, manifest)
    elif args.row_json is not None:
        obj = json.loads(args.row_json.read_text(encoding="utf-8"))
        X = row_from_json(obj, manifest)
    else:
        print("Provide --row-json <file.json> or --from-parquet <file.parquet> [--row-index N]", file=sys.stderr)
        return 1

    proba = clf.predict_proba(X)[0, 1]
    out = {
        "proba_positive": float(proba),
        "score": float(proba),
        "predicted_class": int(clf.predict(X)[0]),
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

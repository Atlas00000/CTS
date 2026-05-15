#!/usr/bin/env python3
"""
Phase 3 Week 5 — export native sklearn Pipeline (joblib) + JSON manifest for Phase 4 handoff.

Format: sklearn + XGBoost in Pipeline (same as train_booster output). ONNX is intentionally not used (§5.3 single path).

Does not touch the EA.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CTS_ML_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402


def _pkg_ver(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export Phase 3 model bundle (joblib + manifest).")
    ap.add_argument("--joblib", type=Path, required=True, help="Trained Pipeline from train_booster (*_xgb.joblib)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=CTS_ML_DIR / "exports" / "phase3_v1",
        help="Output directory (default: cts_ml/exports/phase3_v1)",
    )
    ap.add_argument(
        "--metrics-json",
        type=Path,
        default=None,
        help="Optional copy of train_booster *_metrics.json into bundle",
    )
    ap.add_argument(
        "--calibration-csv",
        type=Path,
        default=None,
        help="Optional copy of *_calibration_val.csv into bundle",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not args.joblib.is_file():
        print(f"joblib not found: {args.joblib}", file=sys.stderr)
        return 1

    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    model_dst = out / "model.joblib"
    shutil.copy2(args.joblib, model_dst)

    manifest: dict = {
        "export_format": "sklearn_pipeline_joblib",
        "manifest_version": 1,
        "cts_schema_version": 1,
        "label_column": "y_has_fill",
        "label_spec": "cts_ml/labeling.md §5.C (would_trade subset in training Parquet)",
        "feature_columns": list(mlc.NUMERIC_FEATURES + mlc.BOOL_FEATURES + mlc.CAT_FEATURES),
        "numeric_columns": list(mlc.NUMERIC_FEATURES),
        "boolean_columns": list(mlc.BOOL_FEATURES),
        "categorical_columns": list(mlc.CAT_FEATURES),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_joblib": str(args.joblib.resolve()),
        "python_packages": {
            "scikit-learn": _pkg_ver("scikit-learn"),
            "xgboost": _pkg_ver("xgboost"),
            "pandas": _pkg_ver("pandas"),
            "joblib": _pkg_ver("joblib"),
        },
        "phase4_hint": "Load model.joblib with joblib; score one row DataFrame with feature_columns (see inference_score_row.py).",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if args.metrics_json and args.metrics_json.is_file():
        shutil.copy2(args.metrics_json, out / "training_metrics.json")
    if args.calibration_csv and args.calibration_csv.is_file():
        shutil.copy2(args.calibration_csv, out / "calibration_val.csv")

    if args.verbose:
        print(f"Wrote {model_dst}", file=sys.stderr)
        print(f"Wrote {out / 'manifest.json'}", file=sys.stderr)
    print(json.dumps({"bundle_dir": str(out.resolve()), "model": str(model_dst.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

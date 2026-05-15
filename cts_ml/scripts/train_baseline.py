#!/usr/bin/env python3
"""
Phase 3 Week 3 — time-ordered sklearn baseline on Parquet from build_dataset.py.

Does not touch the EA. Shared split/features: ml_common.py (same folder).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402


def make_pipeline(model: str, random_state: int) -> Pipeline:
    pre = mlc.make_preprocessor()
    if model == "logistic":
        clf = LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=random_state,
            solver="lbfgs",
        )
    else:
        clf = RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            class_weight="balanced",
            random_state=random_state,
            n_jobs=-1,
        )
    return Pipeline([("prep", pre), ("clf", clf)])


def main() -> int:
    ap = argparse.ArgumentParser(description="CTS sklearn baseline (Phase 3 Week 3).")
    ap.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Parquet from build_dataset.py (default: newest cts_dataset_*.parquet in data/)",
    )
    ap.add_argument(
        "--split-config",
        type=Path,
        default=mlc.DEFAULT_SPLIT,
        help=f"YAML split config (default: {mlc.DEFAULT_SPLIT})",
    )
    ap.add_argument(
        "--auto-split",
        type=float,
        default=None,
        metavar="FRAC",
        help="Ignore YAML row index: use floor(FRAC*n) as train_row_end_exclusive (e.g. 0.7)",
    )
    ap.add_argument(
        "--purge-hours",
        type=int,
        default=None,
        help="Override purge_hours from YAML (default: from YAML or 0)",
    )
    ap.add_argument("--model", choices=("logistic", "rf"), default="rf")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--write-split-config",
        type=Path,
        default=None,
        help="Write computed by_index YAML (use with --auto-split)",
    )
    ap.add_argument(
        "--out-metrics",
        type=Path,
        default=None,
        help="Write metrics JSON (default: print only)",
    )
    ap.add_argument(
        "--out-model",
        type=Path,
        default=None,
        help="Write fitted sklearn Pipeline (joblib) for export_phase3_bundle.py",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    ds = args.dataset
    if ds is None:
        ds = mlc.latest_parquet()

    try:
        df = mlc.load_dataset(ds)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    split_meta: dict = {"dataset": str(ds)}
    try:
        if args.auto_split is not None:
            train_df, val_df, sm = mlc.apply_time_split(
                df,
                split_config=args.split_config,
                auto_split=args.auto_split,
                purge_hours_override=args.purge_hours,
                write_split_config=args.write_split_config,
            )
            split_meta.update(sm)
            if args.write_split_config:
                print(f"Wrote split config {args.write_split_config}")
        else:
            train_df, val_df, sm = mlc.apply_time_split(
                df,
                split_config=args.split_config,
                auto_split=None,
                purge_hours_override=args.purge_hours,
                write_split_config=None,
            )
            split_meta.update(sm)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if len(val_df) < 2:
        print("Validation fold too small after split/purge. Add data or lower train fraction.", file=sys.stderr)
        return 2

    X_tr, y_tr = mlc.build_feature_matrix(train_df)
    X_va, y_va = mlc.build_feature_matrix(val_df)

    clf = make_pipeline(args.model, args.seed)
    clf.fit(X_tr, y_tr)

    if args.out_model is not None:
        args.out_model.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(clf, args.out_model)
        if args.verbose:
            print(f"Wrote model {args.out_model}", file=sys.stderr)

    train_metrics = mlc.eval_split("train", clf, X_tr, y_tr)
    val_metrics = mlc.eval_split("validation", clf, X_va, y_va)

    report = {
        "model": args.model,
        "seed": args.seed,
        "split": split_meta,
        "train_metrics": train_metrics,
        "validation_metrics": val_metrics,
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out_metrics:
        args.out_metrics.parent.mkdir(parents=True, exist_ok=True)
        args.out_metrics.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.out_metrics}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Phase 3 Week 4 — XGBoost booster vs sklearn RF baseline on the same time split.

- Same Parquet + split YAML as Week 3 (ml_common).
- Modest fixed hyperparameters + scale_pos_weight for class imbalance.
- Validation calibration table (CSV, no matplotlib).
- Bucket summaries: symbol; ATR quartiles on validation rows.

Outputs: metrics JSON, calibration CSV, joblib pipeline, optional baseline-only metrics for RF.

Does not touch the EA.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402


def _xgb_params(scale_pos_weight: float, seed: int) -> dict[str, Any]:
    return {
        "n_estimators": 400,
        "max_depth": 4,
        "learning_rate": 0.06,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "min_child_weight": 2.0,
        "reg_lambda": 1.0,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "random_state": seed,
        "n_jobs": -1,
        "scale_pos_weight": scale_pos_weight,
        "verbosity": 0,
    }


def make_rf_reference(seed: int) -> Pipeline:
    pre = mlc.make_preprocessor()
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=6,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1,
    )
    return Pipeline([("prep", pre), ("clf", clf)])


def make_xgb_pipeline(scale_pos_weight: float, seed: int) -> Pipeline:
    pre = mlc.make_preprocessor()
    clf = XGBClassifier(**_xgb_params(scale_pos_weight, seed))
    return Pipeline([("prep", pre), ("clf", clf)])


def write_calibration_csv(
    y_true: np.ndarray,
    proba: np.ndarray,
    path: Path,
    *,
    n_bins: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prob_true, prob_pred = calibration_curve(
        y_true.astype(int),
        proba,
        n_bins=n_bins,
        strategy="uniform",
    )
    pd.DataFrame(
        {
            "mean_predicted_probability": prob_pred,
            "fraction_positive": prob_true,
        }
    ).to_csv(path, index=False)


def bucket_by_symbol(val_df: pd.DataFrame, proba: np.ndarray, y_va: np.ndarray) -> list[dict[str, Any]]:
    v = val_df.reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for sym in sorted(v["symbol"].astype(str).unique()):
        mask = (v["symbol"].astype(str).values == sym).astype(bool)
        if mask.sum() == 0:
            continue
        yt = y_va[mask]
        pr = proba[mask]
        row: dict[str, Any] = {
            "symbol": sym,
            "n": int(mask.sum()),
            "event_rate": float(np.mean(yt)),
            "mean_pred": float(np.mean(pr)),
        }
        if mask.sum() >= 2 and len(np.unique(yt)) >= 2:
            row["pr_auc"] = float(average_precision_score(yt, pr))
        else:
            row["pr_auc"] = None
        rows.append(row)
    return rows


def bucket_by_atr_quartile(val_df: pd.DataFrame, proba: np.ndarray, y_va: np.ndarray) -> list[dict[str, Any]]:
    v = val_df.reset_index(drop=True).copy()
    v["_p"] = proba
    v["_y"] = y_va.astype(float)
    try:
        v["atr_q"] = pd.qcut(v["atr1"], q=4, duplicates="drop")
    except ValueError:
        return []
    out: list[dict[str, Any]] = []
    for name, g in v.groupby("atr_q", observed=False):
        out.append(
            {
                "atr_quartile": str(name),
                "n": int(len(g)),
                "event_rate": float(g["_y"].mean()),
                "mean_pred": float(g["_p"].mean()),
            }
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="CTS XGBoost booster (Phase 3 Week 4).")
    ap.add_argument("--dataset", type=Path, default=None, help="Parquet (default: newest cts_dataset_*.parquet)")
    ap.add_argument("--split-config", type=Path, default=mlc.DEFAULT_SPLIT)
    ap.add_argument("--auto-split", type=float, default=None, metavar="FRAC")
    ap.add_argument("--purge-hours", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--calibration-bins", type=int, default=8)
    ap.add_argument(
        "--out-prefix",
        type=Path,
        default=None,
        help="Prefix for outputs (default: data/boost_<UTC>)",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    ds = args.dataset or mlc.latest_parquet()
    try:
        df = mlc.load_dataset(ds)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    try:
        if args.auto_split is not None:
            train_df, val_df, sm = mlc.apply_time_split(
                df,
                split_config=args.split_config,
                auto_split=args.auto_split,
                purge_hours_override=args.purge_hours,
                write_split_config=None,
            )
        else:
            train_df, val_df, sm = mlc.apply_time_split(
                df,
                split_config=args.split_config,
                auto_split=None,
                purge_hours_override=args.purge_hours,
                write_split_config=None,
            )
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1

    if len(val_df) < 2:
        print("Validation fold too small.", file=sys.stderr)
        return 2

    X_tr, y_tr = mlc.build_feature_matrix(train_df)
    X_va, y_va = mlc.build_feature_matrix(val_df)
    pos = float(np.sum(y_tr))
    neg = float(len(y_tr) - np.sum(y_tr))
    spw = (neg / pos) if pos > 0 else 1.0

    rf = make_rf_reference(args.seed)
    rf.fit(X_tr, y_tr)
    rf_val = mlc.eval_split("rf_validation", rf, X_va, y_va)

    xgb_pipe = make_xgb_pipeline(spw, args.seed)
    xgb_pipe.fit(X_tr, y_tr)
    xgb_train = mlc.eval_split("xgb_train", xgb_pipe, X_tr, y_tr)
    xgb_val = mlc.eval_split("xgb_validation", xgb_pipe, X_va, y_va)

    proba_va = xgb_pipe.predict_proba(X_va)[:, 1]

    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = args.out_prefix or (mlc.DATA_DIR / f"boost_{utc}")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    cal_path = Path(str(prefix) + "_calibration_val.csv")
    metrics_path = Path(str(prefix) + "_metrics.json")
    model_path = Path(str(prefix) + "_xgb.joblib")

    write_calibration_csv(y_va, proba_va, cal_path, n_bins=args.calibration_bins)
    joblib.dump(xgb_pipe, model_path)

    rf_pr = rf_val.get("pr_auc")
    xgb_pr = xgb_val.get("pr_auc")
    beats = None
    if rf_pr is not None and xgb_pr is not None:
        beats = bool(xgb_pr > rf_pr)

    report: dict[str, Any] = {
        "run_id": prefix.name,
        "dataset": str(ds),
        "seed": args.seed,
        "xgb_hyperparams": _xgb_params(spw, args.seed),
        "scale_pos_weight_computed": spw,
        "split": {"dataset": str(ds), **sm},
        "rf_validation_metrics": rf_val,
        "xgb_train_metrics": xgb_train,
        "xgb_validation_metrics": xgb_val,
        "comparison": {
            "validation_pr_auc_rf": rf_pr,
            "validation_pr_auc_xgb": xgb_pr,
            "xgb_beats_rf_on_validation_pr_auc": beats,
            "note": "Small validation sets make this noisy; use more data for firm conclusions.",
        },
        "buckets_validation": {
            "by_symbol": bucket_by_symbol(val_df, proba_va, y_va),
            "by_atr_quartile": bucket_by_atr_quartile(val_df, proba_va, y_va),
        },
        "artifacts": {
            "metrics_json": str(metrics_path),
            "calibration_csv": str(cal_path),
            "xgb_joblib": str(model_path),
        },
    }
    metrics_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.verbose:
        print(f"Wrote {metrics_path}", file=sys.stderr)
        print(f"Wrote {cal_path}", file=sys.stderr)
        print(f"Wrote {model_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

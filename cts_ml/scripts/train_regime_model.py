#!/usr/bin/env python3
"""
Phase 3 Week 6 — optional multiclass RF to predict `regime_rule_v1` from **numeric + symbol/tf only**
(bias/sig booleans excluded so the model is not a trivial copy of the rule inputs).

Uses the same time-ordered split as Week 3 (`ml_common.apply_time_split` + `baseline_split_v1.yaml`).

Does not touch the EA.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ml_common as mlc  # noqa: E402


def make_regime_preprocessor() -> ColumnTransformer:
    numeric_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    cat_pipe = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False, max_categories=32),
            ),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, list(mlc.NUMERIC_FEATURES)),
            ("cat", cat_pipe, list(mlc.CAT_FEATURES)),
        ]
    )


def build_regime_X(df: pd.DataFrame) -> pd.DataFrame:
    X = df[list(mlc.NUMERIC_FEATURES + mlc.CAT_FEATURES)].copy()
    for c in mlc.CAT_FEATURES:
        X[c] = X[c].astype(str)
    for c in mlc.NUMERIC_FEATURES:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    return X


def per_symbol_val_metrics(symbols: np.ndarray, y_true: np.ndarray, y_pred: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym in sorted(np.unique(symbols)):
        m = symbols.astype(str) == str(sym)
        if int(m.sum()) < 2:
            rows.append({"symbol": str(sym), "n": int(m.sum()), "accuracy": None})
            continue
        acc = float(accuracy_score(y_true[m], y_pred[m]))
        rows.append({"symbol": str(sym), "n": int(m.sum()), "accuracy": acc})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Train optional regime multiclass RF (Week 6).")
    ap.add_argument("--dataset", type=Path, required=True, help="Parquet with regime_rule_v1 (use augment_regime_column.py)")
    ap.add_argument("--split-config", type=Path, default=mlc.DEFAULT_SPLIT)
    ap.add_argument("--auto-split", type=float, default=None)
    ap.add_argument("--purge-hours", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-metrics", type=Path, default=None)
    ap.add_argument("--out-model", type=Path, default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not args.dataset.is_file():
        print(f"not found: {args.dataset}", file=sys.stderr)
        return 1

    df = mlc.load_dataset(args.dataset)
    if "regime_rule_v1" not in df.columns:
        print("dataset must contain regime_rule_v1 (run augment_regime_column.py first)", file=sys.stderr)
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
        print("validation too small", file=sys.stderr)
        return 2

    le = LabelEncoder()
    le.fit(pd.concat([train_df["regime_rule_v1"], val_df["regime_rule_v1"]]).astype(str))
    y_tr = le.transform(train_df["regime_rule_v1"].astype(str))
    y_va = le.transform(val_df["regime_rule_v1"].astype(str))
    X_tr = build_regime_X(train_df)
    X_va = build_regime_X(val_df)

    clf = Pipeline(
        [
            ("prep", make_regime_preprocessor()),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=300,
                    max_depth=8,
                    class_weight="balanced",
                    random_state=args.seed,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    clf.fit(X_tr, y_tr)
    pred_tr = clf.predict(X_tr)
    pred_va = clf.predict(X_va)

    report: dict[str, Any] = {
        "task": "regime_rule_v1_multiclass",
        "regime_rule_spec": "scripts/regime_rules.py apply_regime_rule_v1",
        "features_used": list(mlc.NUMERIC_FEATURES + mlc.CAT_FEATURES),
        "label_encoder_classes": list(le.classes_),
        "split": {"dataset": str(args.dataset), **sm},
        "train": {
            "rows": int(len(train_df)),
            "accuracy": float(accuracy_score(y_tr, pred_tr)),
            "f1_macro": float(f1_score(y_tr, pred_tr, average="macro", zero_division=0)),
        },
        "validation": {
            "rows": int(len(val_df)),
            "accuracy": float(accuracy_score(y_va, pred_va)),
            "f1_macro": float(f1_score(y_va, pred_va, average="macro", zero_division=0)),
        },
        "validation_by_symbol": per_symbol_val_metrics(val_df["symbol"].values, y_va, pred_va),
        "train_regime_counts": train_df["regime_rule_v1"].value_counts().to_dict(),
        "val_regime_counts": val_df["regime_rule_v1"].value_counts().to_dict(),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out_metrics:
        args.out_metrics.parent.mkdir(parents=True, exist_ok=True)
        args.out_metrics.write_text(text + "\n", encoding="utf-8")
        if args.verbose:
            print(f"Wrote {args.out_metrics}", file=sys.stderr)
    if args.out_model:
        bundle = {"pipeline": clf, "label_encoder": le, "regime_rule_version": "v1"}
        joblib.dump(bundle, args.out_model)
        if args.verbose:
            print(f"Wrote {args.out_model}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

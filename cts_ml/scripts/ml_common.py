"""
Shared helpers for Phase 3 training scripts (train_baseline.py, train_booster.py).

Import from scripts/ with sys.path adjusted (see each driver script).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

SCRIPT_DIR = Path(__file__).resolve().parent
CTS_ML_DIR = SCRIPT_DIR.parent
DATA_DIR = CTS_ML_DIR / "data"
DEFAULT_SPLIT = CTS_ML_DIR / "configs" / "baseline_split_v1.yaml"

NUMERIC_FEATURES = (
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
)
BOOL_FEATURES = ("bias_long", "bias_short", "sig_long", "sig_short")
CAT_FEATURES = ("symbol", "tf")


def latest_parquet() -> Path:
    paths = sorted(DATA_DIR.glob("cts_dataset_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        raise FileNotFoundError(f"No cts_dataset_*.parquet under {DATA_DIR}")
    return paths[0]


def load_split_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def temporal_split_by_index(
    df: pd.DataFrame,
    *,
    train_row_end_exclusive: int,
    purge_hours: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    n = len(df)
    end = max(1, min(train_row_end_exclusive, n - 1))
    train = df.iloc[:end].copy()
    val = df.iloc[end:].copy()
    meta: dict[str, Any] = {
        "train_rows": int(len(train)),
        "val_rows_initial": int(len(val)),
        "train_ts_max": None,
        "val_ts_min_after_purge": None,
    }
    if len(train):
        meta["train_ts_max"] = pd.Timestamp(train["ts_gmt"].max()).isoformat()
    if purge_hours > 0 and len(train) and len(val):
        cutoff = pd.Timestamp(train["ts_gmt"].max()) + pd.Timedelta(hours=purge_hours)
        val = val[val["ts_gmt"] > cutoff].copy()
    if len(val):
        meta["val_ts_min_after_purge"] = pd.Timestamp(val["ts_gmt"].min()).isoformat()
    meta["val_rows"] = int(len(val))
    return train, val, meta


def temporal_split_auto(
    df: pd.DataFrame,
    *,
    train_frac: float,
    purge_hours: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], int]:
    n = len(df)
    end = max(1, min(int(n * train_frac), n - 1))
    train, val, meta = temporal_split_by_index(df, train_row_end_exclusive=end, purge_hours=purge_hours)
    meta["train_row_end_exclusive"] = end
    return train, val, meta, end


def build_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    miss = [c for c in NUMERIC_FEATURES + BOOL_FEATURES + CAT_FEATURES if c not in df.columns]
    if miss:
        raise ValueError(f"dataset missing columns: {miss}")
    X = df[list(NUMERIC_FEATURES + BOOL_FEATURES + CAT_FEATURES)].copy()
    for c in BOOL_FEATURES:
        X[c] = X[c].astype(bool).astype(np.int8)
    for c in CAT_FEATURES:
        X[c] = X[c].astype(str)
    y = df["y_has_fill"].astype(bool).values
    return X, y


def make_preprocessor() -> ColumnTransformer:
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
            ("num", numeric_pipe, list(NUMERIC_FEATURES)),
            ("cat", cat_pipe, list(CAT_FEATURES)),
            ("bool", "passthrough", list(BOOL_FEATURES)),
        ]
    )


def eval_split(name: str, clf: Pipeline, X: pd.DataFrame, y: np.ndarray) -> dict[str, Any]:
    out: dict[str, Any] = {"split": name, "rows": int(len(y))}
    if len(y) == 0:
        out["note"] = "empty"
        return out
    pos_rate = float(np.mean(y))
    out["positive_rate"] = pos_rate
    if len(np.unique(y)) < 2:
        out["note"] = "single_class"
        proba = clf.predict_proba(X)[:, 1] if hasattr(clf, "predict_proba") else None
        if proba is not None:
            out["brier"] = float(brier_score_loss(y, proba))
        return out
    proba = clf.predict_proba(X)[:, 1]
    out["pr_auc"] = float(average_precision_score(y, proba))
    out["brier"] = float(brier_score_loss(y, proba))
    try:
        out["log_loss"] = float(log_loss(y, proba, labels=[False, True]))
    except ValueError:
        out["log_loss"] = None
    return out


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path)
    if "ts_gmt" not in df.columns or "y_has_fill" not in df.columns:
        raise ValueError("dataset must include ts_gmt and y_has_fill")
    return df.sort_values("ts_gmt", kind="mergesort").reset_index(drop=True)


def apply_time_split(
    df: pd.DataFrame,
    *,
    split_config: Path,
    auto_split: float | None,
    purge_hours_override: int | None,
    write_split_config: Path | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return train_df, val_df, split_meta (same semantics as train_baseline main)."""
    split_meta: dict[str, Any] = {"rows": int(len(df))}
    if auto_split is not None:
        if auto_split <= 0 or auto_split >= 1:
            raise ValueError("--auto-split must be in (0,1)")
        ph = purge_hours_override if purge_hours_override is not None else 0
        train_df, val_df, sm, end = temporal_split_auto(df, train_frac=auto_split, purge_hours=ph)
        split_meta.update(sm)
        split_meta["mode"] = "auto_frac"
        split_meta["train_frac"] = auto_split
        if write_split_config:
            cfg = {
                "version": 1,
                "mode": "by_index",
                "sort_by": "ts_gmt",
                "train_row_end_exclusive": end,
                "purge_hours": ph,
            }
            write_split_config.parent.mkdir(parents=True, exist_ok=True)
            with write_split_config.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg, fh, sort_keys=False)
        return train_df, val_df, split_meta

    if not split_config.is_file():
        raise FileNotFoundError(split_config)
    cfg = load_split_config(split_config)
    if cfg.get("mode") != "by_index":
        raise ValueError("Only mode: by_index is supported in this version.")
    purge = int(cfg.get("purge_hours", 0))
    if purge_hours_override is not None:
        purge = purge_hours_override
    end = int(cfg["train_row_end_exclusive"])
    train_df, val_df, sm = temporal_split_by_index(df, train_row_end_exclusive=end, purge_hours=purge)
    split_meta.update(sm)
    split_meta["mode"] = "yaml_by_index"
    split_meta["split_config"] = str(split_config)
    split_meta["purge_hours"] = purge
    return train_df, val_df, split_meta

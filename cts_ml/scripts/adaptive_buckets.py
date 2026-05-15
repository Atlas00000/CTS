"""
Phase 5 — bucket assignment (ATR quartiles + regime_rule_v1).

ATR edges are fit on the training slice only (no leakage into validation labels).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from regime_rules import apply_regime_rule_v1

CTS_ML_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ADAPTIVE = CTS_ML_DIR / "configs" / "adaptive_v1.yaml"

ATR_LABELS = ("q1_low", "q2", "q3", "q4_high")


def load_adaptive_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def save_adaptive_config(path: Path, cfg: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, default_flow_style=False, sort_keys=False)


def fit_atr_edges(train_atr: pd.Series) -> list[float]:
    """Return three quantile edges for pd.cut (25/50/75% on train)."""
    s = train_atr.dropna()
    if len(s) < 4:
        raise ValueError(f"Need at least 4 train rows with atr1; got {len(s)}")
    edges = [float(s.quantile(q)) for q in (0.25, 0.5, 0.75)]
    # Strict monotonicity for pd.cut
    for i in range(1, len(edges)):
        if edges[i] <= edges[i - 1]:
            edges[i] = edges[i - 1] + 1e-12
    return edges


def assign_atr_quartile(atr: pd.Series, edges: list[float], labels: tuple[str, ...] = ATR_LABELS) -> pd.Series:
    if len(edges) != 3:
        raise ValueError("atr_quartile.edges must have exactly 3 values (four bins)")
    bins = [-np.inf, edges[0], edges[1], edges[2], np.inf]
    out = pd.cut(atr, bins=bins, labels=list(labels), include_lowest=True)
    return out.astype(str)


def assign_bucket_id(
    df: pd.DataFrame,
    *,
    bucket_mode: str,
    atr_col: str = "atr_quartile",
    regime_col: str = "regime_rule_v1",
) -> pd.Series:
    mode = bucket_mode.strip().lower()
    if mode == "atr_quartile":
        return df[atr_col].astype(str)
    if mode == "regime_rule_v1":
        return df[regime_col].astype(str)
    if mode == "combined":
        return df[atr_col].astype(str) + "|" + df[regime_col].astype(str)
    raise ValueError(f"Unknown bucket_mode: {bucket_mode!r}")


def augment_buckets(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    edges: list[float] | None = None,
) -> tuple[pd.DataFrame, list[float]]:
    """Add regime_rule_v1, atr_quartile, bucket_id. Returns (df, edges used)."""
    out = df.copy()
    labels = tuple(cfg.get("atr_quartile", {}).get("labels", list(ATR_LABELS)))
    if len(labels) != 4:
        raise ValueError("atr_quartile.labels must have 4 entries")

    out["regime_rule_v1"] = apply_regime_rule_v1(out)

    use_edges = edges
    if use_edges is None:
        stored = cfg.get("atr_quartile", {}).get("edges") or []
        if len(stored) == 3:
            use_edges = [float(x) for x in stored]
    if use_edges is None or len(use_edges) != 3:
        raise ValueError("Provide atr edges (fit on train) or set atr_quartile.edges in config")

    out["atr_quartile"] = assign_atr_quartile(out["atr1"], use_edges, labels=labels)
    out["bucket_id"] = assign_bucket_id(
        out,
        bucket_mode=str(cfg.get("bucket_mode", "combined")),
    )
    return out, use_edges


def frequency_table(df: pd.DataFrame, col: str, split: str) -> pd.DataFrame:
    vc = df[col].value_counts(dropna=False).sort_index()
    total = max(int(len(df)), 1)
    return pd.DataFrame(
        {
            "split": split,
            "bucket": vc.index.astype(str),
            "count": vc.values,
            "pct": (vc.values / total * 100.0).round(2),
        }
    )


def summarize_frequencies(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    bucket_mode: str,
) -> pd.DataFrame:
    parts = [
        frequency_table(train_df, "bucket_id", "train"),
        frequency_table(val_df, "bucket_id", "val"),
    ]
    if bucket_mode in ("atr_quartile", "combined"):
        parts.extend(
            [
                frequency_table(train_df, "atr_quartile", "train"),
                frequency_table(val_df, "atr_quartile", "val"),
            ]
        )
    if bucket_mode in ("regime_rule_v1", "combined"):
        parts.extend(
            [
                frequency_table(train_df, "regime_rule_v1", "train"),
                frequency_table(val_df, "regime_rule_v1", "val"),
            ]
        )
    return pd.concat(parts, ignore_index=True)

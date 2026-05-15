"""Build feature row from JSON + run sklearn Pipeline (same rules as inference_score_row.py)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from phase4_api.errors import MissingFeaturesError


def missing_feature_keys(row: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    cols: list[str] = list(manifest["feature_columns"])
    return [c for c in cols if c not in row]


def features_to_frame(row: dict[str, Any], manifest: dict[str, Any]) -> pd.DataFrame:
    miss = missing_feature_keys(row, manifest)
    if miss:
        raise MissingFeaturesError(miss)
    cols: list[str] = list(manifest["feature_columns"])
    out = pd.DataFrame([{c: row[c] for c in cols}])
    for c in manifest.get("boolean_columns", []):
        out[c] = out[c].astype(bool).astype(np.int8)
    for c in manifest.get("categorical_columns", []):
        out[c] = out[c].astype(str)
    for c in manifest.get("numeric_columns", []):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def score_positive_proba(clf: Any, manifest: dict[str, Any], row: dict[str, Any]) -> float:
    X = features_to_frame(row, manifest)
    proba = clf.predict_proba(X)[0, 1]
    return float(proba)

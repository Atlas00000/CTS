"""Phase 5 — load adaptive_v1.yaml and resolve per-bucket threshold / risk."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

from phase4_api.errors import MissingFeaturesError

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from adaptive_buckets import (  # noqa: E402
    assign_atr_quartile,
    assign_bucket_id,
    load_adaptive_config,
)
from regime_rules import apply_regime_rule_v1  # noqa: E402

_REGIME_COLS = (
    "ema_fast_1",
    "ema_slow_1",
    "macd_main1",
    "macd_sig1",
    "bias_long",
    "bias_short",
)
_BUCKET_COLS = ("atr1", *_REGIME_COLS)


class AdaptivePolicyResolver:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path.resolve()
        self.cfg = load_adaptive_config(self.config_path)

    @property
    def version(self) -> int:
        return int(self.cfg.get("version", 1))

    def missing_bucket_keys(self, features: dict[str, Any]) -> list[str]:
        return [c for c in _BUCKET_COLS if c not in features]

    def resolve(self, features: dict[str, Any]) -> dict[str, Any]:
        miss = self.missing_bucket_keys(features)
        if miss:
            raise MissingFeaturesError(miss)

        row = pd.DataFrame([{c: features[c] for c in _BUCKET_COLS}])
        row["regime_rule_v1"] = apply_regime_rule_v1(row)

        atr_cfg = self.cfg.get("atr_quartile", {})
        edges = atr_cfg.get("edges") or []
        if len(edges) != 3:
            raise ValueError(
                f"adaptive config {self.config_path}: atr_quartile.edges must have 3 values"
            )
        labels = tuple(atr_cfg.get("labels", ("q1_low", "q2", "q3", "q4_high")))
        row["atr_quartile"] = assign_atr_quartile(
            pd.to_numeric(row["atr1"], errors="coerce"),
            [float(x) for x in edges],
            labels=labels,
        )
        row["bucket_id"] = assign_bucket_id(
            row,
            bucket_mode=str(self.cfg.get("bucket_mode", "combined")),
        )

        bucket_id = str(row["bucket_id"].iloc[0])
        policies = self.cfg.get("policies", {})
        default = policies.get("default", {"threshold": 0.65, "risk_multiplier": 1.0})
        by_bucket: dict[str, Any] = policies.get("by_bucket", {})
        pol = dict(by_bucket.get(bucket_id, default))

        return {
            "bucket_id": bucket_id,
            "regime_rule_v1": str(row["regime_rule_v1"].iloc[0]),
            "atr_quartile": str(row["atr_quartile"].iloc[0]),
            "threshold": float(pol.get("threshold", default.get("threshold", 0.65))),
            "risk_multiplier": float(pol.get("risk_multiplier", default.get("risk_multiplier", 1.0))),
        }


def load_resolver(config_path: Path) -> AdaptivePolicyResolver:
    if not config_path.is_file():
        raise FileNotFoundError(f"adaptive config not found: {config_path}")
    return AdaptivePolicyResolver(config_path)

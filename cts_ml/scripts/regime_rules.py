"""
Phase 3 Week 6 — deterministic regime labels from **logged signal-row features only** (no new EA fields).

`regime_rule_v1` (string):
- **trend_long:** EMA fast > slow, MACD main > signal, and **bias_long** (Classic stack alignment).
- **trend_short:** EMA fast < slow, MACD main < signal, and **bias_short**.
- **chop:** everything else (mixed stack, flat MACD cross, or bias not aligned with EMA/MACD).

This is a **rule tag** for analysis / optional second model — not a traded label.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_regime_rule_v1(df: pd.DataFrame) -> pd.Series:
    need = ("ema_fast_1", "ema_slow_1", "macd_main1", "macd_sig1", "bias_long", "bias_short")
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"apply_regime_rule_v1: missing columns {miss}")

    ema_bull = df["ema_fast_1"] > df["ema_slow_1"]
    ema_bear = df["ema_fast_1"] < df["ema_slow_1"]
    macd_bull = df["macd_main1"] > df["macd_sig1"]
    macd_bear = df["macd_main1"] < df["macd_sig1"]
    bl = df["bias_long"].astype(bool)
    bs = df["bias_short"].astype(bool)

    long_stack = ema_bull & macd_bull & bl
    short_stack = ema_bear & macd_bear & bs
    both = long_stack & short_stack
    out = pd.Series(
        np.select(
            [long_stack & ~both, short_stack & ~both],
            ["trend_long", "trend_short"],
            default="chop",
        ),
        index=df.index,
    )
    return out.astype(str)

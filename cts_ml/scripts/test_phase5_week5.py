#!/usr/bin/env python3
"""Phase 5 Week 5 — risk multiplier clamp + filter logic checks.

  cd cts_ml
  python scripts/test_phase5_week5.py
"""

from __future__ import annotations

import sys
from pathlib import Path

CTS_ML = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CTS_ML))


def apply_risk_multiplier(lots: float, mult: float, mult_min: float, mult_max: float) -> float:
    m = mult
    if mult_min > 0 and m < mult_min:
        m = mult_min
    if mult_max > 0 and m > mult_max:
        m = mult_max
    return lots * m


def filter_allow(score: float, thr_eff: float) -> bool:
    return score >= thr_eff


def main() -> int:
    fails = 0

    # Adaptive thr 0.63 vs fixed 0.65: score 0.64 passes 0.63 but fails 0.65
    if not filter_allow(0.64, 0.63):
        print("0.64 should pass thr_eff 0.63")
        fails += 1
    if filter_allow(0.64, 0.65):
        print("0.64 should fail thr_eff 0.65")
        fails += 1

    # Risk clamp
    out = apply_risk_multiplier(0.10, 0.85, 0.50, 1.50)
    if abs(out - 0.085) > 1e-9:
        print("risk mult 0.85 failed", out)
        fails += 1
    out2 = apply_risk_multiplier(0.10, 2.0, 0.50, 1.50)
    if abs(out2 - 0.15) > 1e-9:
        print("risk mult cap failed", out2)
        fails += 1

    mq5 = CTS_ML.parent / "CTS.mq5"
    if not mq5.is_file():
        fails += 1
    else:
        t = mq5.read_text(encoding="utf-8", errors="replace")
        for needle in ("InpAiApplyRiskMultiplier", "CTS_ApplyRiskMultiplier", "1.13"):
            if needle not in t:
                print(f"missing in CTS.mq5: {needle}")
                fails += 1

    changelog = CTS_ML.parent / "CHANGELOG-adaptive.md"
    if not changelog.is_file():
        print("missing CHANGELOG-adaptive.md")
        fails += 1

    print("FAIL" if fails else "PASS Week 5")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())

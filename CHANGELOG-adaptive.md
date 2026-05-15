# Adaptive policy changelog (Phase 5)

## v1.16 — 2026-05-15 (dev defaults)

- EA inputs reset for **EA-first development**: `InpUseAiGate=false`, tester mocks off (`-1`).
- Phase 5 tester sign-off recorded below; **live API deployment deferred**.

## v1.15 — 2026-05-15 (Week 5 complete — tester)

- **Filter:** per-bucket **`thr_eff`** from API or tester mock.
- **Sizing (optional):** `InpAiApplyRiskMultiplier` + clamps.
- **Ops:** `cts_ml/docs/adaptive_ops.md` (quarterly review, rollback).

### Strategy Tester sign-off (EURUSD M5, 2026-01-01 → 2026-05-14)

Log: `MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\logs\20260515.log`

| Wall-clock | Test | Mode | Mock score | thr_eff | Risk mult | Final balance | Notes |
|------------|------|------|------------|---------|-----------|---------------|--------|
| 13:26 | **A** Shadow adaptive | SHADOW | 0.70 | 0.63 | 1.0 | **4855.80** | 45 AiGate lines; trades open |
| 13:28 | **B** Filter block | FILTER | 0.10 | 0.65 | 1.0 | **5000.00** | 45 FILTER BLOCK; no trades |
| 13:37 | **C** Filter @ 0.63 | FILTER | 0.60 | 0.63 | 1.0 | **5000.00** | `score < thr_eff=0.6300` × 45 |
| 13:38 | **D** Shadow + sizing | SHADOW | 0.70 | 0.63 | 0.85 | **4884.64** | 35× `lots 0.10 -> 0.08` |

**Deferred to deployment:** live chart + uvicorn + non-mock WebRequest.

## v1.13 — 2026-05-15 (Week 5 code)

- Tester mock inputs for threshold, bucket, risk_multiplier.

## v1.12 — 2026-05-15 (Week 4)

- Journal: `bucket=`, `thr_eff=`, `risk_mult=` on AiGate lines.

## v1.0 policy YAML

- `cts_ml/configs/adaptive_v1.yaml` — combined ATR + regime buckets, train-fit edges.

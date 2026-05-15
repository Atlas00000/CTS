# Adaptive policy — operations (Phase 5 Week 5)

## Rollout order

1. **Shadow** on live chart (`InpAiGateMode=CTS_AI_SHADOW`, API + `CTS_ADAPTIVE_CONFIG`).
2. Review journal: `bucket=`, `thr_eff=`, `allow=`.
3. **Filter** (`CTS_AI_FILTER`) when shadow looks correct.
4. **Risk multiplier** (`InpAiApplyRiskMultiplier=true`) only after filter is stable.

## Quarterly review (suggested)

| Step | Action |
|------|--------|
| 1 | Rebuild Parquet (`build_dataset.py`) from latest Postgres/CSV |
| 2 | `assign_buckets.py --write-cutpoints` |
| 3 | `analyze_buckets.py --write-policies -v` |
| 4 | Diff `configs/adaptive_v1.yaml`; set `effective_from` |
| 5 | Restart uvicorn; re-run shadow on chart 1–2 weeks |

## Rollback

1. Revert `configs/adaptive_v1.yaml` (git) or restore known-good copy.
2. Restart API: `uvicorn phase4_api.app:app` from `cts_ml/`.
3. EA: set `InpAiGateMode=CTS_AI_SHADOW` or `InpUseAiGate=false`.
4. No EA recompile required for YAML-only threshold changes if already on v1.12+.

## Host env

```env
CTS_ADAPTIVE_CONFIG=../configs/adaptive_v1.yaml
CTS_PHASE3_MODEL=../exports/phase3_v1/model.joblib
```

## Tester (no HTTP)

Use mock inputs; see `cts_ml/README.md` Phase 5 Week 5.

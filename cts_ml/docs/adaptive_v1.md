# Adaptive policy v1 (Phase 5)

## Buckets (Week 1)

- **Mode:** `combined` → `bucket_id = {atr_quartile}|{regime_rule_v1}` (e.g. `q3|trend_long`).
- **ATR edges:** fit on **train rows only** (see `configs/baseline_split_v1.yaml`), stored in `configs/adaptive_v1.yaml`.

## Evidence (Week 2)

Per-bucket **train** `fill_rate` = share of rows with `y_has_fill` (order matched).  
`proxy_plus_1r_rate` is reported when `fill_entry_price` exists; legacy rows may be NaN.

## Threshold rule (static v1)

| Train fill_rate | AI threshold |
|-----------------|--------------|
| ≥ 0.78 | 0.60 |
| ≥ 0.72 | 0.63 |
| ≥ 0.68 | 0.65 (default) |
| ≥ 0.62 | 0.68 |
| &lt; 0.62 | 0.72 |

Buckets with **&lt; 5** train rows use **default** only.  
**risk_multiplier:** `0.85` when train fill_rate &lt; 0.62, else `1.0`.

## Rationale

- Stricter threshold in weaker buckets reduces AI-approved trades when historical fill quality is lower.
- Slightly looser threshold in strong buckets (high fill_rate) avoids over-filtering aligned trend contexts.
- No online learning; change YAML + restart API (Week 3+) after quarterly review.

## Regenerate

```powershell
cd cts_ml
python scripts\analyze_buckets.py -i data\cts_dataset_adaptive_v1.parquet --write-policies -v
```

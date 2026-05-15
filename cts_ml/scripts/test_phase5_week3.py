#!/usr/bin/env python3
"""Phase 5 Week 3 exit tests — adaptive policy on POST /score and POST /policy.

  cd cts_ml
  python scripts/test_phase5_week3.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CTS_ML = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CTS_ML))

os.environ.setdefault("CTS_PHASE3_MODEL", str(CTS_ML / "exports" / "phase3_v1" / "model.joblib"))
os.environ.setdefault("CTS_AI_THRESHOLD", "0.65")
os.environ.setdefault("CTS_SCORE_TIMEOUT_MS", "200")
os.environ.setdefault("CTS_ADAPTIVE_CONFIG", str(CTS_ML / "configs" / "adaptive_v1.yaml"))

from fastapi.testclient import TestClient  # noqa: E402

from phase4_api.app import app  # noqa: E402


def _pick_parquet() -> Path | None:
    for name in (
        "cts_dataset_adaptive_v1.parquet",
        "cts_dataset_merged_2026-05-15.parquet",
        "cts_dataset_7y_2026-05-15.parquet",
    ):
        p = CTS_ML / "data" / name
        if p.is_file():
            return p
    cand = sorted((CTS_ML / "data").glob("cts_dataset_*.parquet"), key=lambda x: x.stat().st_mtime, reverse=True)
    return cand[0] if cand else None


def main() -> int:
    fails = 0
    with TestClient(app, raise_server_exceptions=False) as client:
        h = client.get("/health")
        print("GET /health", h.status_code, h.text)
        if h.status_code != 200:
            return 1
        hj = h.json()
        if not hj.get("adaptive_enabled"):
            print("adaptive_enabled is false")
            fails += 1
        if hj.get("adaptive_version") != 1:
            print("unexpected adaptive_version", hj.get("adaptive_version"))
            fails += 1

        pq = _pick_parquet()
        if pq is None:
            print("No parquet; skip row tests")
            return fails

        import pandas as pd

        row = pd.read_parquet(pq).iloc[0]
        fr = client.get("/features")
        cols = fr.json()["feature_columns"]
        body = json.loads(json.dumps({k: row[k] for k in cols}, default=str))

        pol = client.post("/policy", json=body)
        print("POST /policy", pol.status_code, pol.text)
        bid: str | None = None
        thr = 0.65
        if pol.status_code != 200:
            fails += 1
        else:
            pj = pol.json()
            bid = pj.get("bucket_id")
            if not bid or "|" not in bid:
                print("bad bucket_id", bid)
                fails += 1
            thr = float(pj["threshold"])
            if thr < 0.5 or thr > 0.9:
                print("threshold out of range", thr)
                fails += 1

        sc = client.post("/score", json=body)
        print("POST /score", sc.status_code, sc.text[:200])
        if sc.status_code != 200:
            fails += 1
        else:
            sj = sc.json()
            if bid is not None and sj.get("bucket_id") != bid:
                print("bucket_id mismatch score vs policy")
                fails += 1
            if abs(float(sj["threshold"]) - thr) > 1e-9:
                print("threshold mismatch score vs policy")
                fails += 1
            if sj.get("would_allow") != (float(sj["score"]) >= float(sj["threshold"])):
                print("would_allow inconsistent")
                fails += 1

        # Second row (if any) should be stable for same features
        df = pd.read_parquet(pq)
        if len(df) > 1:
            body2 = json.loads(json.dumps({k: df.iloc[0][k] for k in cols}, default=str))
            p2 = client.post("/policy", json=body2)
            if p2.status_code == 200 and p2.json().get("bucket_id") != bid:
                print("same row unstable bucket", p2.json())
                fails += 1

    print("FAIL" if fails else "PASS Week 3")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())

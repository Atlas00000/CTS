#!/usr/bin/env python3
"""Phase 4 Week 2 exit tests (TestClient; no running uvicorn required).

  cd cts_ml
  python scripts/test_phase4_week2.py
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

from fastapi.testclient import TestClient  # noqa: E402

from phase4_api.app import app  # noqa: E402


def main() -> int:
    fails = 0
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/features")
        print("GET /features", r.status_code)
        if r.status_code != 200:
            print(r.text)
            return 1
        cols = r.json()["feature_columns"]
        assert len(cols) > 0

        bad = client.post("/score", json={"symbol": "EURUSD"})
        print("POST /score missing keys", bad.status_code, bad.text)
        if bad.status_code != 422:
            fails += 1
        else:
            j = bad.json()
            if "missing_keys" not in j or not j["missing_keys"]:
                fails += 1

        pq = CTS_ML / "data" / "cts_dataset_7y_2026-05-15.parquet"
        if not pq.is_file():
            cand = sorted((CTS_ML / "data").glob("cts_dataset_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
            pq = cand[0] if cand else None
        if pq is None:
            print("No parquet; skip happy path")
            return fails

        import pandas as pd

        row = pd.read_parquet(pq).iloc[0]
        body = json.loads(json.dumps({k: row[k] for k in cols}, default=str))
        ok = client.post("/score", json=body)
        print("POST /score full row", ok.status_code, ok.text)
        if ok.status_code != 200:
            fails += 1
        else:
            j = ok.json()
            for key in ("score", "threshold", "would_allow", "inference_ms"):
                if key not in j:
                    print(f"missing response key {key}")
                    fails += 1
            if j.get("inference_ms", 999) > 200:
                print("Warning: inference_ms > 200 (server budget); still OK on slow host")

    print("FAIL" if fails else "PASS Week 2")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())

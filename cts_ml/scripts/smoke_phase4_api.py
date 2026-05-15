#!/usr/bin/env python3
"""Quick smoke: GET /health (and POST /score if model exists). Run from cts_ml/:

  pip install -r requirements.txt -r phase4_api/requirements_phase4.txt
  python scripts/smoke_phase4_api.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CTS_ML = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CTS_ML))

# Defaults for local dev if .env not loaded
os.environ.setdefault("CTS_PHASE3_MODEL", str(CTS_ML / "exports" / "phase3_v1" / "model.joblib"))
os.environ.setdefault("CTS_AI_THRESHOLD", "0.65")

from fastapi.testclient import TestClient  # noqa: E402

# Import app after env (lifespan loads model)
from phase4_api.app import app  # noqa: E402


def main() -> int:
    with TestClient(app, raise_server_exceptions=False) as client:
        h = client.get("/health")
        print("GET /health", h.status_code, h.text)
        if h.status_code != 200:
            return 1
        j = h.json()
        if not j.get("model_loaded"):
            print("Note: model not loaded — export bundle to exports/phase3_v1/ or set CTS_PHASE3_MODEL.", file=sys.stderr)
            return 0
        # one row from parquet if present
        pq = CTS_ML / "data" / "cts_dataset_7y_2026-05-15.parquet"
        if not pq.is_file():
            cand = sorted((CTS_ML / "data").glob("cts_dataset_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
            pq = cand[0] if cand else None
        if pq is None or not pq.is_file():
            print("No Parquet for /score body; health-only smoke OK.")
            return 0
        man = Path(j["manifest_path"])
        if not man.is_file():
            print("manifest missing", file=sys.stderr)
            return 0
        import pandas as pd

        df = pd.read_parquet(pq)
        row = df.iloc[0].to_dict()
        manifest = json.loads(man.read_text(encoding="utf-8"))
        keys = manifest["feature_columns"]
        body = {k: row[k] for k in keys if k in row}
        for k in keys:
            if k not in body:
                print(f"Missing column {k} in parquet row0", file=sys.stderr)
                return 1
        # JSON-serializable: numpy scalars
        body = json.loads(json.dumps(body, default=str))
        r = client.post("/score", json=body)
        print("POST /score", r.status_code, r.text)
        if r.status_code != 200:
            return 1
        sj = r.json()
        if "inference_ms" not in sj:
            print("missing inference_ms in /score response", file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

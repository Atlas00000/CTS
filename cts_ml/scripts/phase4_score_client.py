#!/usr/bin/env python3
"""Phase 4 Week 2 — call live POST /score (requires uvicorn on 127.0.0.1:8008).

  cd cts_ml
  python -m uvicorn phase4_api.app:app --host 127.0.0.1 --port 8008
  python scripts/phase4_score_client.py --from-parquet data\\cts_dataset_7y_2026-05-15.parquet --row-index 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import httpx
except ImportError:
    print("pip install httpx (or phase4_api/requirements_phase4.txt)", file=sys.stderr)
    raise SystemExit(1) from None

import pandas as pd

CTS_ML = Path(__file__).resolve().parent.parent


def row_body_from_parquet(path: Path, index: int, feature_columns: list[str]) -> dict:
    df = pd.read_parquet(path)
    if index < 0 or index >= len(df):
        raise IndexError(f"row index {index} out of range (n={len(df)})")
    row = df.iloc[index]
    body: dict = {}
    for k in feature_columns:
        if k not in row.index:
            raise ValueError(f"parquet missing column {k}")
        v = row[k]
        if hasattr(v, "item"):
            v = v.item()
        body[k] = v
    return json.loads(json.dumps(body, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description="POST /score against running Phase 4 API.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8008")
    ap.add_argument("--from-parquet", type=Path, required=True)
    ap.add_argument("--row-index", type=int, default=0)
    ap.add_argument(
        "--timeout-ms",
        type=int,
        default=500,
        help="HTTP client timeout (should exceed server CTS_SCORE_TIMEOUT_MS)",
    )
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    timeout = args.timeout_ms / 1000.0

    with httpx.Client(base_url=base, timeout=timeout) as client:
        h = client.get("/health")
        print("GET /health", h.status_code, h.text)
        if h.status_code != 200:
            return 1
        feat = client.get("/features")
        if feat.status_code != 200:
            print("GET /features failed", feat.status_code, feat.text, file=sys.stderr)
            return 1
        cols = feat.json()["feature_columns"]
        body = row_body_from_parquet(args.from_parquet, args.row_index, cols)
        t0 = time.perf_counter()
        r = client.post("/score", json=body)
        wall_ms = (time.perf_counter() - t0) * 1000.0
        print(f"POST /score {r.status_code} wall_ms={wall_ms:.1f}")
        print(r.text)
        if r.status_code != 200:
            return 1
        data = r.json()
        if wall_ms > args.timeout_ms:
            print("Warning: wall time exceeded --timeout-ms", file=sys.stderr)
        print(
            f"score={data['score']:.4f} threshold={data['threshold']} "
            f"would_allow={data['would_allow']} inference_ms={data.get('inference_ms')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

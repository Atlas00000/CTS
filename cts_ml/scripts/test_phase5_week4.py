#!/usr/bin/env python3
"""Phase 5 Week 4 — EA contract: API fields + JSON parse mirror of CTS_AiGate.mqh.

  cd cts_ml
  python scripts/test_phase5_week4.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CTS_ML = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CTS_ML))

os.environ.setdefault("CTS_PHASE3_MODEL", str(CTS_ML / "exports" / "phase3_v1" / "model.joblib"))
os.environ.setdefault("CTS_ADAPTIVE_CONFIG", str(CTS_ML / "configs" / "adaptive_v1.yaml"))

from fastapi.testclient import TestClient  # noqa: E402

from phase4_api.app import app  # noqa: E402


def parse_json_double(body: str, key: str) -> float | None:
    needle = f'"{key}":'
    pos = body.find(needle)
    if pos < 0:
        return None
    pos += len(needle)
    end = body.find(",", pos)
    if end < 0:
        end = body.find("}", pos)
    if end < 0:
        return None
    return float(body[pos:end].strip())


def parse_json_string(body: str, key: str) -> str | None:
    needle = f'"{key}":'
    pos = body.find(needle)
    if pos < 0:
        return None
    pos += len(needle)
    if body[pos : pos + 4] == "null":
        return ""
    if body[pos] != '"':
        return None
    pos += 1
    end = body.find('"', pos)
    if end < 0:
        return None
    return body[pos:end]


def effective_threshold(thr_api: float, thr_ea: float = 0.65) -> float:
    if 0.0 < thr_api <= 1.0:
        return thr_api
    return thr_ea


def _pick_parquet() -> Path | None:
    for name in ("cts_dataset_adaptive_v1.parquet", "cts_dataset_merged_2026-05-15.parquet"):
        p = CTS_ML / "data" / name
        if p.is_file():
            return p
    cand = sorted((CTS_ML / "data").glob("cts_dataset_*.parquet"), key=lambda x: x.stat().st_mtime, reverse=True)
    return cand[0] if cand else None


def main() -> int:
    fails = 0
    sample = (
        '{"score":0.21,"threshold":0.63,"would_allow":false,'
        '"bucket_id":"q4_high|trend_long","risk_multiplier":1.0}'
    )
    bid = parse_json_string(sample, "bucket_id")
    thr = parse_json_double(sample, "threshold")
    if bid != "q4_high|trend_long" or thr != 0.63:
        print("parse mirror failed on sample JSON")
        fails += 1

    thr_eff = effective_threshold(thr or 0.0)
    allow = 0.21 >= thr_eff
    if allow or thr_eff != 0.63:
        print("allow/thr_eff logic failed", allow, thr_eff)
        fails += 1

    log_pat = re.compile(
        r"bucket=q4_high\|trend_long thr_eff=0\.6300.*allow=false"
    )
    fake_log = (
        "CTS AiGate: signal_id=x side=BUY score=0.2100 bucket=q4_high|trend_long "
        "thr_eff=0.6300 thr_ea=0.6500 risk_mult=1.00 allow=false shadow=true src=http http=200 reason=shadow"
    )
    if not log_pat.search(fake_log):
        print("log format pattern failed")
        fails += 1

    with TestClient(app, raise_server_exceptions=False) as client:
        pq = _pick_parquet()
        if pq is None:
            print("No parquet; skip API row test")
            return fails

        import pandas as pd

        row = pd.read_parquet(pq).iloc[0]
        cols = client.get("/features").json()["feature_columns"]
        body = json.loads(json.dumps({k: row[k] for k in cols}, default=str))
        r = client.post("/score", json=body)
        if r.status_code != 200:
            print("POST /score failed", r.status_code, r.text)
            fails += 1
            return fails

        raw = r.text
        j = r.json()
        bid2 = parse_json_string(raw, "bucket_id") or j.get("bucket_id")
        thr2 = parse_json_double(raw, "threshold") or j.get("threshold")
        if not bid2 or "|" not in bid2:
            print("API missing bucket_id")
            fails += 1
        te = effective_threshold(float(thr2))
        score = float(j["score"])
        if (score >= te) != bool(j["would_allow"]):
            print("would_allow vs score/thr_eff mismatch", score, te, j["would_allow"])
            fails += 1

    mq5 = CTS_ML.parent / "CTS.mq5"
    aigate = CTS_ML.parent / "Include" / "CTS_AiGate.mqh"
    for p in (mq5, aigate):
        if not p.is_file():
            print(f"missing {p}")
            fails += 1
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
            if "thr_eff" not in text or "bucket_id" not in text:
                print(f"Week4 markers missing in {p.name}")
                fails += 1

    print("FAIL" if fails else "PASS Week 4")
    return fails


if __name__ == "__main__":
    raise SystemExit(main())

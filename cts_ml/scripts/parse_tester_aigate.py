#!/usr/bin/env python3
"""Summarize CTS AiGate lines from Strategy Tester journal log.

  python scripts/parse_tester_aigate.py path/to/20260515.log
  python scripts/parse_tester_aigate.py path/to/20260515.log --since 13:09:26
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

LINE = re.compile(
    r"CTS AiGate: signal_id=.* score=([\d.]+) bucket=([^ ]+) thr_eff=([\d.]+).*"
    r"allow=(true|false) shadow=(true|false).*reason=(\S+)"
)
BLOCK = re.compile(r"FILTER BLOCK")
INIT_MOCK = re.compile(r"tester MOCK score=([\d.]+) thr_eff=([\d.]+)")
FINAL = re.compile(r"final balance ([\d.]+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--since", type=str, default=None, help="Wall-clock prefix e.g. 13:09:26")
    args = ap.parse_args()

    text = args.log.read_text(encoding="utf-16-le", errors="replace")
    if "CTS AiGate" not in text:
        text = args.log.read_text(encoding="utf-8", errors="replace")

    signals = 0
    blocks = 0
    allows = 0
    last_bal = None
    mock_init = None

    for line in text.splitlines():
        if args.since and args.since not in line[:20]:
            continue
        m = INIT_MOCK.search(line)
        if m:
            mock_init = (float(m.group(1)), float(m.group(2)))
        if BLOCK.search(line):
            blocks += 1
        lm = LINE.search(line)
        if lm:
            signals += 1
            if lm.group(4) == "true":
                allows += 1
        bm = FINAL.search(line)
        if bm:
            last_bal = float(bm.group(1))

    print(f"log: {args.log}")
    if mock_init:
        print(f"init mock: score={mock_init[0]} thr_eff={mock_init[1]}")
    print(f"signal lines: {signals}  allow=true: {allows}  FILTER BLOCK lines: {blocks}")
    if last_bal is not None:
        print(f"last final balance: {last_bal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

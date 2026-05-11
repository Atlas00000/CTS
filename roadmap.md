# CTS EA — Phase 1 Roadmap

Automated **execution engine** only: indicators, signals on closed bars, market orders, basic risk, and configuration. No strategy research loop, no AI, no session/portfolio layers, no pending orders or pyramiding (per `concept.md`).

---

## Scope guardrails (do not expand)

**In scope**

- Scaffold EA + small `.mqh` modules (indicators, signals, risk, trade helper, state/log as needed—split only where it reduces clutter).
- Inputs: symbol/chart defaults, TF selection, EMA/MACD parameters, risk (fixed lot / % risk), SL/TP modes, spread, slippage, magic, permissions, max trades, cooldown, equity guard.
- Signal pipeline: new bar only, closed-bar values, rules from **Gaps answered** in `concept.md` (bias, EMA cross, MACD main vs signal cross, symmetric shorts).
- Execution: `CTrade` (or equivalent) market buy/sell, validation before send, clear logging on failure.
- State: cooldown, position counts by magic/symbol, optional “one position per direction” flags if you add them—keep behind simple inputs.

**Out of scope until a later phase**

- Pending orders, scaling, grid/martingale/hedge logic.
- Session filters, news filters, multi-symbol portfolio, ML/optimization automation.
- Extra indicators “for confirmation,” divergence, zero-line MACD rules, histogram-only entries.
- Fancy abstractions (plugin registry, scriptable DSL, dynamic loading) unless a single file exceeds maintainability—default is **flat and boring**.

---

## Definition of done (“point of complete”)

Phase 1 is **complete** when all of the following are true:

1. EA compiles and runs on chart and in **Strategy Tester** without errors.
2. On **each new bar** of the configured signal timeframe, the EA evaluates bias → EMA cross → MACD cross using **closed-bar** logic only (no tick-based signal flips).
3. When all entry conditions and guards pass, it sends **one** appropriate market order with SL/TP (or RR-derived TP) per your configured rules.
4. Guards work: max spread, max positions, cooldown, buy/sell permissions, basic equity/balance check, magic attribution.
5. Lot sizing: fixed mode works; % risk mode works when SL distance is defined (document any broker constraint failures in logs).
6. Parameters are grouped inputs; defaults match `concept.md` (e.g. `UseCurrentChartTF = true`, MACD 12/26/9).
7. You can hand a second person `concept.md` + this roadmap and they can verify behavior from logs and tester reports—no tribal knowledge required.

---

## Weekly implementation plan

### Week 1 — Scaffold and configuration shell

- Create EA skeleton (`OnInit` / `OnDeinit` / `OnTick`): no trading yet.
- Add **input groups**: symbol/chart flags, signal timeframe, indicator periods, MACD params, risk block, trade limits, magic, logging verbosity.
- Implement **`IsNewBar()`** (or timer-based bar check) for the **signal** timeframe; main evaluation runs only on new bar.
- Stub functions: `IndicatorsUpdate()`, `EvaluateSignals()`, `TryOpenTrade()` returning early with comments or logs.
- **Exit:** EA loads, logs “initialized” and “new bar” markers; no orders placed.

### Week 2 — Indicators and data plumbing

- `OnInit`: create handles for 200 EMA, 50 EMA, MACD on the **selected** timeframe/symbol.
- On new bar: `CopyBuffer` enough history (minimum 3–5 bars) for cross detection on bar **1** vs **2** (shift indexing consistent with MQL5: closed bar = 1).
- Validate handle errors and missing bars; log once per failure type.
- **Exit:** On tester/chart, logs show consistent EMA/MACD values on each new bar; no trades yet.

### Week 3 — Signal engine (no execution)

- Encode **long/short bias** and **EMA50/EMA200 cross** exactly as in `concept.md` (prev closed vs current closed).
- Encode **MACD main vs signal cross** on closed bars; respect “do not use” list.
- Implement **Entry bar alignment (Phase 1 — resolved)** in `concept.md`: bias at shift `1`; EMA cross and MACD cross both confirmed on the **same** `2` → `1` step; **no** N-bar lookback for staged signals.
- Combine into `ShouldEnterLong()` / `ShouldEnterShort()` (or one struct result + enum).
- **Exit:** Visual or log output of “would enter long/short” on historical bars matches manual spot-checks on a few dates.

### Week 4 — Risk, sizing, and order placement

- Position size: fixed lots; optional % of equity with SL distance in price → normalize to volume step/min/max.
- SL/TP: fixed points/pips and/or RR from SL; optional ATR path only if already specified—keep one code path, disable with input if unused.
- Pre-trade checks: spread, stops level / freeze, margin, permissions, max trades, cooldown.
- Execute market order with magic and comment; handle retcodes; log failures.
- **Exit:** Controlled tester runs open/close positions with correct SL/TP and lots; failures are logged, not silent.

### Week 5 — State, safety, and tester hardening

- Cooldown: bars and/or minutes from `concept.md`; persist “last trade time” in memory (Phase 1 sufficient).
- Max simultaneous trades and optional per-direction cap—query positions by magic + symbol.
- Equity/balance floor: simple input threshold; block new entries when breached (define whether to manage open positions or only block new—document choice).
- Slippage deviation on order send per symbol capabilities.
- Run multi-symbol/timeframe smoke tests in tester; fix off-by-one bar indexing if signals drift.
- **Exit:** Repeated signals do not spam orders; guards visibly trigger in logs.

### Week 6 — Completion pass (buffer week if Weeks 1–5 slipped)

- Code read-through: remove dead code, align names with `concept.md`, ensure no tick-heavy work remains.
- Final tester pass: minimum forward/backward sanity on M1/M5 as per your Phase 1 focus; confirm determinism (same inputs → same trades in tester).
- Optional: save a default `.set` preset file for repeatable tests—not required for “complete,” but useful.
- **Exit:** Definition of done checklist above is fully checked.

If your schedule is tight, **merge Week 6 into Week 5** by keeping Week 5 scope strictly to hardening only (no new features).

---

## Principles while building

- Prefer **explicit conditionals** and small helpers over new class hierarchies.
- Every new feature must pass: “Is this required for **automated execution** of the defined rules?” If not, defer.
- When in doubt, **log** the reason a trade was skipped instead of adding another filter.

---

## Reference

- Full rules and “Gaps answered”: `concept.md`

---

## Optional workflow: build first, then test

If you prefer a single implementation pass before dedicated tester work: follow Weeks 1–5 in order without intermediate tester milestones, then run the **Definition of done** checklist and Strategy Tester once at the end. **Compile first:** MetaEditor → Open `CTS.mq5` → Compile; or command-line compile (produces `CTS.log` next to the source). Paste any **errors/warnings from `CTS.log`** (or the Errors tool window) into chat for fixes—`information:` lines can be ignored.

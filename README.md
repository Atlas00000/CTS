# CTS — Classic Trend Stack (MT5 Expert Advisor)

**CTS** is a MetaTrader 5 Expert Advisor that implements a **trend-stack** style entry model: **two EMAs** (fast / slow) for bias and crossover confirmation, plus **MACD main vs signal line** for timing. **Phase 1** is an **execution engine**: market entries, configurable risk, guards, and modular code—**not** session filters, portfolio logic, ML, or pending-order workflows.

**Repository:** [https://github.com/Atlas00000/CTS](https://github.com/Atlas00000/CTS)

---

## What this EA does

| Area | Behavior |
|------|----------|
| **Orders** | **Market buy/sell only** (no pending orders, scaling, grid, martingale, hedging logic). |
| **When it evaluates** | **On each new bar** of the configured **signal timeframe** (`OnTick` returns early until `iTime(sym, tf, 0)` changes). |
| **Signal timing** | Uses **closed-bar** values only (no tick-based cross detection). |
| **Symbol** | **Single symbol** per chart instance; default uses **current chart symbol**. Optional manual symbol string when disabled. |
| **Timeframe** | Indicators and signals use **current chart period** by default, or a **manual** `ENUM_TIMEFRAMES` when `InpUseCurrentChartTF = false`. |

---

## Strategy logic (implemented rules)

The EA follows the **same-bar alignment** rule documented in `concept.md`:

1. **Signal bar** = last **fully closed** bar (MQL5 shift **`1`**); **previous** closed bar = shift **`2`**.
2. **Long bias** on bar `1`: close **above** slow EMA; fast EMA **above** slow EMA.
3. **Bullish EMA cross** on the step **2 → 1**: `EMA_fast[2] ≤ EMA_slow[2]` and `EMA_fast[1] > EMA_slow[1]`.
4. **Bullish MACD cross** on the **same** **2 → 1** step: MACD main **≤** signal at `2`, MACD main **>** signal at `1`.
5. **Short** is the symmetric mirror (close below slow EMA, fast below slow, bearish EMA cross, bearish MACD cross).

If **both** long and short conditions were ever true on one bar, the EA **skips** (safety).

**Classic narrative** (50 / 200 EMA + MACD 12, 26, 9) is the *conceptual* stack in `concept.md`. **Shipped defaults** use **shorter** periods (**21 / 55** EMA, **8 / 17 / 7** MACD) so **M1/M5** backtests produce **more trades** for data collection; restore **50 / 200** and **12 / 26 / 9** in inputs anytime for the classic stack.

---

## Risk and execution

| Feature | Notes |
|---------|--------|
| **Position size** | **Fixed lots**, or **% of equity at risk** per trade (`OrderCalcProfit` + SL distance). Volume is normalized to broker **min / max / step**. |
| **Stop loss** | **Fixed** distance in **points** (not pips label—uses `SYMBOL_POINT`), or **ATR × multiplier** on signal bar `1` when SL mode is ATR. |
| **Take profit** | **Fixed points** from entry, or **risk–reward multiple** of the SL distance (RR mode). |
| **Guards** | Max **spread** (points), **slippage** deviation, **max open positions** (by magic + symbol), optional **one position total** / **one per direction**, **buy/sell only** filter, optional **minimum equity** floor, **cooldown** in bars and/or minutes since last entry. |
| **Stops validation** | SL/TP checked vs **stops level** and side of market before send. |
| **Magic & comment** | Magic number input; positions opened with comment **`CTS`**. |

Enums live in `Include/CTS_Config.mqh` (`ENUM_CTS_SL_MODE`, `ENUM_CTS_TP_MODE`, `ENUM_CTS_TRADE_DIR`).

---

## Project layout

```
CTS/
├── CTS.mq5              # Expert entrypoint, inputs, orchestration
├── CTS.mqproj             # MetaEditor project
├── concept.md             # Full spec + “Gaps answered”
├── roadmap.md             # Phase 1 build roadmap
├── README.md              # This file
└── Include/
    ├── CTS_Config.mqh    # Enums (direction, SL/TP modes)
    ├── CTS_Log.mqh       # Verbose logging helper
    ├── CTS_State.mqh     # New-bar detection, cooldown state
    ├── CTS_Indicators.mqh# iMA / iMACD / iATR handles + buffer copy
    ├── CTS_Signals.mqh   # Long/short boolean rules
    ├── CTS_Risk.mqh      # Lots, SL/TP prices, stop-distance checks
    └── CTS_Trade.mqh     # CTrade wrapper, guards, position counts
```

---

## Inputs (reference)

### Symbol and timeframe

| Input | Default | Purpose |
|--------|---------|---------|
| `InpUseCurrentChartSymbol` | `true` | Use `_Symbol`; if `false`, use trimmed `InpManualSymbol`. |
| `InpManualSymbol` | `""` | Override symbol when not using chart symbol. |
| `InpUseCurrentChartTF` | `true` | Use `Period()` for signals; if `false`, use `InpManualTF`. |
| `InpManualTF` | `PERIOD_M5` | Manual signal timeframe. |

### Indicators

| Input | Default | Purpose |
|--------|---------|---------|
| `InpEMAFast` | `21` | Fast EMA period (concept “50” when using classic). |
| `InpEMASlow` | `55` | Slow EMA period (concept “200” when using classic). |
| `InpMacdFast` / `InpMacdSlow` / `InpMacdSignal` | `8` / `17` / `7` | MACD parameters (classic: 12 / 26 / 9). |
| `InpATRPeriod` | `10` | ATR period (SL mode ATR and buffer fill). |

### Risk and sizing

| Input | Default | Purpose |
|--------|---------|---------|
| `InpUseRiskPercent` | `false` | Toggle risk-based sizing. |
| `InpRiskPercent` | `1.0` | Equity % to risk when enabled. |
| `InpFixedLots` | `0.10` | Lot size when not using risk %. |
| `InpSLMode` | Fixed | `CTS_SL_FIXED` or `CTS_SL_ATR`. |
| `InpSLPoints` | `200` | SL distance in **points** (fixed mode). |
| `InpATRMultSL` | `1.5` | SL = ATR(bar 1) × multiplier (ATR mode). |
| `InpTPMode` | RR | `CTS_TP_FIXED` or `CTS_TP_RR`. |
| `InpTPPoints` | `200` | TP distance in points (fixed TP mode). |
| `InpTPRiskReward` | `2.0` | TP distance = SL distance × RR (RR mode). |

### Execution guards

| Input | Default | Purpose |
|--------|---------|---------|
| `InpMagic` | `260051` | Magic number for orders and position queries. |
| `InpMaxSpreadPoints` | `50` | Block entry if spread (ask−bid)/point exceeds this; `0` disables. |
| `InpSlippagePoints` | `30` | `CTrade::SetDeviationInPoints`. |
| `InpMaxOpenTrades` | `1` | Cap concurrent positions (magic + symbol); `0` = no cap. |
| `InpCooldownBars` | `0` | Minimum bars since entry signal bar before next entry. |
| `InpCooldownMinutes` | `0` | Wall-clock cooldown after an entry. |
| `InpTradeDirection` | Both | `CTS_DIR_BOTH`, `CTS_DIR_BUY_ONLY`, `CTS_DIR_SELL_ONLY`. |
| `InpOnePositionPerDir` | `false` | At most one buy and/or one sell. |
| `InpOnePositionTotal` | `true` | At most one position total (recommended with max trades 1). |
| `InpMinEquity` | `0.0` | Block new entries if equity below this; `0` disables. |

### Debug

| Input | Default | Purpose |
|--------|---------|---------|
| `InpVerboseLog` | `true` | Logs every new bar when no signal (noisy in tester—set `false` for long runs). |

---

## Installation and build

1. Copy the **`CTS`** folder into your terminal’s **MQL5 data folder** under **`Experts`**  
   (e.g. `%AppData%\MetaQuotes\Terminal\<instance>\MQL5\Experts\CTS\`).
2. Open **`CTS.mq5`** in **MetaEditor** and **Compile** (F7).  
3. Attach **`CTS`** from the Navigator to a chart, or select it in the **Strategy Tester**.

**Version** is set in `#property version` inside `CTS.mq5` (currently **1.01**).

---

## Testing tips

- Use **Strategy Tester** with **Every tick** or **1 minute OHLC** according to how strictly you want intrabar SL/TP fills; signals still only update **once per new bar** of the signal timeframe.
- For long date ranges, set **`InpVerboseLog = false`** to avoid huge journals.
- Save **`.set`** presets from the tester’s **Inputs** tab for repeatable runs (classic vs sensitive defaults).

---

## Documentation in repo

| File | Content |
|------|---------|
| [concept.md](concept.md) | Product vision, Phase 1 scope, detailed signal definitions, entry bar alignment. |
| [roadmap.md](roadmap.md) | Weekly implementation plan and definition of done. |

---

## Disclaimer

This software is for **education and research**. Trading carries **risk of loss**. Past backtest results do not guarantee future performance. You are responsible for compliance with broker rules and local regulations.

---

## License

See copyright / `#property` lines in `CTS.mq5`. Add a SPDX or license file if you want a standard open-source license.

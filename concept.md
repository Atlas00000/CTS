We are building an MT5 Expert Advisor (EA) centered around the following trading concept and system architecture:
[1. The Classic Trend Stack
Indicators: 200 EMA + 50 EMA + MACD
How it works:
200 EMA defines the macro bias — only trade long above it, short below it
50 EMA confirms intermediate trend direction
MACD crossover on signal line provides entry timing
Entry logic: Price above 200 EMA → 50 EMA crosses above 200 EMA → MACD crosses bullish → Long entry reverse for short
Why it works: Filters out counter-trend noise at every layer. Widely backtested across forex, equities, and indices. The 200 EMA is respected by institutions.
Best on: Daily and 4H charts | Trending pairs/instruments. Weakness: Heavy lag; in ranging markets generates repeated false crossovers]
Current Development Scope (Phase 1):
The focus right now is strictly on building the automated execution engine based on the selected indicators and signal logic. We are intentionally keeping the system lightweight and modular at this stage.
Important:
Do NOT introduce advanced filtering, AI layers, session filters, portfolio management, adaptive optimization, or overengineered logic yet.
Do NOT add unnecessary complexity outside the core execution workflow.
The goal is simply to automate trade execution reliably using the selected indicators and trading conditions.
Core Objective:
Build a configurable execution engine capable of:
Reading indicator values and market conditions in real time
Evaluating entry conditions
Executing buy/sell trades automatically
Managing basic trade risk
Providing clean parameter configuration for optimization and future scaling
Execution Engine Requirements:
Configurable indicator inputs
Configurable entry conditions
Buy/sell execution logic
Support for market orders initially
Clean order validation before execution
Low-latency and lightweight processing
Modular architecture for future expansion
Basic Risk Management & Position Sizing:
Include foundational risk and trade management features only, such as:
Fixed lot size input
Optional risk-based position sizing (% risk per trade)
Stop Loss (fixed points/pips or ATR-based if applicable)
Take Profit configuration
Risk-to-reward ratio support
Maximum spread filter
Slippage control
Maximum simultaneous open trades
Basic cooldown between trades
Magic number management
Equity/balance safety checks
Configurable trading permissions (buy only / sell only / both)
The EA should:
Be modular and extensible
Use clean separation of concerns
Support future integration of:
filters
session logic
AI optimization
volatility layers
portfolio controls
advanced trade management
multi-strategy routing
Architecture Goals:
Clean and maintainable codebase
Production-style folder structure
Clear module responsibilities
Configurable engine design
Scalable architecture without premature complexity
High execution reliability
Easy debugging and testing
Suggested Focus Areas:
Signal evaluation pipeline
Indicator management system
Trade execution module
Risk management module
Position sizing engine
Configuration/input management
Logging and debugging utilities
State and trade tracking
What I need from you:
Design the execution engine architecture
Define module responsibilities and execution workflow
Recommend an MT5 production-grade folder structure
Suggest industry best practices for EA development
Keep implementation practical, scalable, and efficient
Avoid unnecessary abstraction or feature creep
Prioritize configurability, maintainability, and execution reliability
The current objective is NOT strategy perfection or advanced intelligence.
The objective is building a strong configurable execution foundation first.





Gaps answered

- **Primary Timeframes (Phase 1)**
  - Initial optimization focus: **M1 and M5**
  - EA must support configurable timeframe selection through inputs
  - Timeframe input options:
    - Current Chart Timeframe
    - Manual Timeframe Selection (M1, M5, M15, M30, H1, H4, D1, etc.)
  - Default setting:
    - `UseCurrentChartTF = true`
- **Symbol Handling**
  - Phase 1 operates as a **single-pair EA**
  - Symbol selection options:
    - Current chart symbol
    - Optional manual symbol override later
  - Default:
    - `UseCurrentChartSymbol = true`
  - User attaches EA directly to selected pair chart
- **Signal Definition (Critical for Backtest Consistency)**
  - EMA cross logic evaluated on:
    - **Closed candle only**
    - No intra-candle/tick crossover validation
  - Signals processed:
    - **On new bar only**
    - Prevents duplicate entries and repaint-style behavior
  - One signal generated per valid crossover event
  - Cross confirmation definition:
    - Bullish cross:
      - Previous closed candle:
        - `EMA50 <= EMA200`
      - Current closed candle:
        - `EMA50 > EMA200`
    - Bearish cross:
      - Previous closed candle:
        - `EMA50 >= EMA200`
      - Current closed candle:
        - `EMA50 < EMA200`
- **Trend Bias Rules**
  - Long bias:
    - Price close above 200 EMA
    - 50 EMA above 200 EMA
  - Short bias:
    - Price close below 200 EMA
    - 50 EMA below 200 EMA
  - Bias checked on candle close
- **MACD Specification**
  - Default MACD settings:
    - Fast EMA = 12
    - Slow EMA = 26
    - Signal SMA = 9
  - All parameters configurable through inputs
  - Entry trigger method:
    - **MACD Main Line crossing Signal Line**
  - Bullish MACD trigger:
    - Previous bar:
      - MACD Main <= Signal
    - Current closed bar:
      - MACD Main > Signal
  - Bearish MACD trigger:
    - Previous bar:
      - MACD Main >= Signal
    - Current closed bar:
      - MACD Main < Signal
  - Do NOT use:
    - Histogram-only logic
    - Zero-line confirmation
    - Divergence logic
    - Multi-layer MACD filters (Phase 1)
- **Entry bar alignment (Phase 1 — resolved)**
  - Evaluation runs **once per new bar** on the configured signal timeframe.
  - **Signal bar** = the bar that **just closed** (in MQL5 terms: use shift **`1`** for “current closed” values; shift **`2`** for “previous closed” when detecting a crossover vs the prior bar).
  - **Same-bar rule (no lookback window):** A long or short entry is allowed only if **every** strategy condition below is satisfied using **that same signal bar**:
    - Bias (price vs EMA200, EMA50 vs EMA200) is read at the **signal bar close** (shift `1`).
    - The **EMA50/EMA200 cross** is confirmed on the **transition into** the signal bar: previous vs signal bar (shifts `2` → `1`) exactly as in **Cross confirmation definition** above.
    - The **MACD main/signal cross** is confirmed on the **same** transition (shifts `2` → `1`) exactly as in **MACD Specification** above.
  - There is **no** separate “EMA cross allowed within last N bars” window in Phase 1. If the EMA cross and MACD cross do not both complete on the **same** bar-to-bar step into the signal bar, **no entry**.
  - Guards (spread, cooldown, max trades, permissions, equity) are evaluated at order time on the same tick as the signal evaluation; they do not change the bar alignment rule above.
- **Long Entry Conditions**
  - Price close above 200 EMA
  - EMA50 above EMA200
  - Valid bullish EMA cross on the signal bar (shifts `2` → `1`, per **Cross confirmation definition**)
  - MACD bullish signal-line crossover on the **same** signal bar (shifts `2` → `1`, per **MACD Specification**)
  - Spread within allowed threshold
  - Cooldown conditions satisfied
  - Max open trades not exceeded
  - Execute market buy order
- **Short Entry Conditions (Symmetric Logic)**
  - Price close below 200 EMA
  - EMA50 below EMA200
  - Valid bearish EMA cross on the signal bar (shifts `2` → `1`, per **Cross confirmation definition**)
  - MACD bearish signal-line crossover on the **same** signal bar (shifts `2` → `1`, per **MACD Specification**)
  - Spread within allowed threshold
  - Cooldown conditions satisfied
  - Max open trades not exceeded
  - Execute market sell order
- **Trade Frequency Rules**
  - One trade per signal
  - Optional:
    - One open position per direction
    - One total open position per symbol
  - Configurable cooldown:
    - Example:
      - `CooldownBars = X`
      - `CooldownMinutes = X`
- **Execution Model**
  - Market execution only (Phase 1)
  - No pending orders initially
  - No scaling-in
  - No pyramiding
  - No grid/martingale behavior
  - No hedging logic
- **Basic Risk Management**
  - Fixed lot mode
  - Optional % risk sizing mode
  - Configurable SL:
    - Fixed pips/points
    - Optional ATR-based mode
  - Configurable TP:
    - Fixed RR ratio
    - Fixed points/pips
  - Safety protections:
    - Max spread filter
    - Slippage control
    - Equity protection
    - Max simultaneous trades
    - Trading direction permissions
- **EA Processing Model**
  - Lightweight event-driven architecture
  - Main logic executes:
    - On new candle only
  - Tick processing minimized
  - Indicator handles initialized once in `OnInit()`
  - Indicator buffers updated efficiently
  - Avoid recalculating unnecessary data every tick
- **Core Design Philosophy**
  - Reliability first
  - Deterministic signals
  - Backtest consistency
  - Clean modular architecture
  - Configurable but not overengineered
  - Built as a scalable execution foundation for future enhancements


//+------------------------------------------------------------------+
//| CTS.mq5 — Classic Trend Stack execution (Phase 1)                |
//| See concept.md / roadmap.md                                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      ""
#property version   "1.16"

#include <Trade/Trade.mqh>

#include "Include/CTS_Config.mqh"
#include "Include/CTS_Log.mqh"
#include "Include/CTS_LogCsv.mqh"
#include "Include/CTS_AiGate.mqh"
#include "Include/CTS_State.mqh"
#include "Include/CTS_Risk.mqh"
#include "Include/CTS_Signals.mqh"
#include "Include/CTS_Trade.mqh"

//--- inputs
input group "Symbol & timeframe"
input bool              InpUseCurrentChartSymbol = true;
input string            InpManualSymbol        = "";
input bool              InpUseCurrentChartTF   = true;
input ENUM_TIMEFRAMES   InpManualTF            = PERIOD_M5;

// Defaults: faster periods for M1/M5 so crosses/MACD fire more often (more sample trades). Use 50/200 + 12/26/9 for the classic stack.
input group "Indicators"
input int               InpEMAFast             = 21;
input int               InpEMASlow             = 55;
input int               InpMacdFast            = 8;
input int               InpMacdSlow            = 17;
input int               InpMacdSignal          = 7;
input int               InpATRPeriod           = 10;

input group "Risk & sizing"
input bool              InpUseRiskPercent      = false;
input double            InpRiskPercent         = 1.0;
input double            InpFixedLots           = 0.10;
input ENUM_CTS_SL_MODE  InpSLMode              = CTS_SL_FIXED;
input int               InpSLPoints            = 200;
input double            InpATRMultSL           = 1.5;
input ENUM_CTS_TP_MODE  InpTPMode              = CTS_TP_RR;
input int               InpTPPoints            = 200;
input double            InpTPRiskReward        = 2.0;

input group "Execution guards"
input long              InpMagic               = 260051;
input int               InpMaxSpreadPoints     = 50;
input int               InpSlippagePoints        = 30;
input int               InpMaxOpenTrades        = 1;
input int               InpCooldownBars         = 0;
input int               InpCooldownMinutes      = 0;
input ENUM_CTS_TRADE_DIR InpTradeDirection      = CTS_DIR_BOTH;
input bool              InpOnePositionPerDir  = false;
input bool              InpOnePositionTotal     = true;
input double            InpMinEquity           = 0.0;

input group "Logging (Phase 2)"
input bool              InpLogCsvEnable        = true;   // default: on for tester CSV + ML pipeline
input bool              InpLogCsvTestRow       = true;
input string            InpLogCsvSubdir        = "CTS_logs";
input bool              InpLogSignals          = true;   // Week 2+: signal rows
input bool              InpLogOrders           = true;   // Week 3+: execution rows
input bool              InpLogInTester         = true;   // Strategy Tester -> CTS_logs_tester
input int               InpLogTesterMaxRows    = 0;       // 0 = unlimited (full long backtests)
input string            InpLogTesterSubdir     = "CTS_logs_tester";

input group "AI gate (Phase 4)"
input bool                  InpUseAiGate            = false;  // dev default: EA runs without AI; enable for Phase 4/5 tests
input ENUM_CTS_AI_GATE_MODE InpAiGateMode           = CTS_AI_SHADOW;
input bool                  InpUseAiGateInTester    = false;
input double                InpAiMockScoreInTester  = -1.0;   // tester mock: 0..1, or <0 = off
input double                InpAiMockThresholdInTester = -1.0;
input string                InpAiMockBucketInTester = "";
input double                InpAiMockRiskMultiplierInTester = -1.0;
input bool                  InpAiApplyRiskMultiplier  = false;
input double                InpAiRiskMultMin          = 0.50;
input double                InpAiRiskMultMax          = 1.50;
input string                InpAiEndpoint           = "http://127.0.0.1:8008/score";
input int                   InpAiTimeoutMs          = 500;
input double                InpAiThreshold          = 0.65;     // EA fallback; filter uses API thr_eff when present

input group "Debug"
input bool              InpVerboseLog          = true;

//---
CTrade g_trade;

//+------------------------------------------------------------------+
bool CTS_AiGate_IsShadowMode(const ENUM_CTS_AI_GATE_MODE mode)
  {
   return (mode == CTS_AI_SHADOW);
  }

//+------------------------------------------------------------------+
string CTS_WorkSymbol()
  {
   if(InpUseCurrentChartSymbol)
      return _Symbol;
   string s = InpManualSymbol;
   StringTrimLeft(s);
   StringTrimRight(s);
   return s;
  }

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES CTS_SignalTimeframe()
  {
   if(InpUseCurrentChartTF)
      return (ENUM_TIMEFRAMES)Period();
   return InpManualTF;
  }

//+------------------------------------------------------------------+
bool CTS_ValidateInputs(string &err)
  {
   err = "";
   if(InpEMAFast <= 0 || InpEMASlow <= 0 || InpEMAFast >= InpEMASlow)
     {
      err = "Invalid EMA periods";
      return false;
     }
   if(InpMacdFast <= 0 || InpMacdSlow <= 0 || InpMacdSignal <= 0)
     {
      err = "Invalid MACD parameters";
      return false;
     }
   if(InpATRPeriod <= 0)
     {
      err = "ATR period must be > 0";
      return false;
     }
   if(InpUseRiskPercent)
     {
      if(InpRiskPercent <= 0.0 || InpRiskPercent > 100.0)
        {
         err = "Risk percent must be in (0,100]";
         return false;
        }
     }
   else
     {
      if(InpFixedLots <= 0.0)
        {
         err = "Fixed lots must be > 0 when not using risk percent";
         return false;
        }
     }
   if(InpSLMode == CTS_SL_FIXED && InpSLPoints <= 0)
     {
      err = "SL points must be > 0 in fixed SL mode";
      return false;
     }
   if(InpSLMode == CTS_SL_ATR && InpATRMultSL <= 0.0)
     {
      err = "ATR multiplier must be > 0";
      return false;
     }
   if(InpTPMode == CTS_TP_FIXED && InpTPPoints <= 0)
     {
      err = "TP points must be > 0 in fixed TP mode";
      return false;
     }
   if(InpTPMode == CTS_TP_RR && InpTPRiskReward <= 0.0)
     {
      err = "TP RR must be > 0";
      return false;
     }
   if(!InpUseCurrentChartSymbol)
     {
      string s = CTS_WorkSymbol();
      if(StringLen(s) == 0)
        {
         err = "Manual symbol empty";
         return false;
        }
      if(!SymbolSelect(s, true))
        {
         err = "SymbolSelect failed for " + s;
         return false;
        }
     }
   if(InpLogCsvEnable)
     {
      string sd = InpLogCsvSubdir;
      string le = "";
      if(!CTS_LogCsv_SanitizeSubdir(sd, le))
        {
         err = le;
         return false;
        }
      string tsd = InpLogTesterSubdir;
      if(!CTS_LogCsv_SanitizeSubdir(tsd, le))
        {
         err = le;
         return false;
        }
      if(InpLogTesterMaxRows < 0)
        {
         err = "Log CSV: tester max rows must be >= 0 (0 = no cap)";
         return false;
        }
     }
   if(InpUseAiGate)
     {
      if(InpAiTimeoutMs < 50)
        {
         err = "AiGate timeout must be >= 50 ms";
         return false;
        }
      string ae = "";
      if(!CTS_AiGate_ValidateEndpoint(InpAiEndpoint, ae))
        {
         err = ae;
         return false;
        }
      string me = "";
      if(!CTS_AiGate_ValidateMockScore(InpAiMockScoreInTester, me))
        {
         err = me;
         return false;
        }
      if(!CTS_AiGate_ValidateMockScore(InpAiMockThresholdInTester, me))
        {
         err = "AiGate mock effective threshold: " + me;
         return false;
        }
      if(InpAiMockRiskMultiplierInTester >= 0.0)
        {
         if(InpAiMockRiskMultiplierInTester < InpAiRiskMultMin || InpAiMockRiskMultiplierInTester > InpAiRiskMultMax)
           {
            err = StringFormat("AiGate mock risk_multiplier must be in [%.2f, %.2f] or <0 off",
                               InpAiRiskMultMin, InpAiRiskMultMax);
            return false;
           }
        }
      if(InpAiRiskMultMin <= 0.0 || InpAiRiskMultMax < InpAiRiskMultMin)
        {
         err = "AiGate risk mult clamps: need 0 < min <= max";
         return false;
        }
      if(InpAiThreshold < 0.0 || InpAiThreshold > 1.0)
        {
         err = "AiGate threshold must be in [0,1]";
         return false;
        }
     }
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_TryOpen(const bool is_long, const CTSPriceBuf &buf, const string sym, const ENUM_TIMEFRAMES tf,
                 const string signal_id)
  {
   string reason = "";
   if(!CTS_CooldownOk(sym, tf, InpCooldownBars, InpCooldownMinutes, InpVerboseLog, reason))
      return false;

   const bool want_long = is_long;
   const bool want_short = !is_long;
   if(!CTS_GuardsCommon(sym, InpMaxSpreadPoints, InpMinEquity, InpTradeDirection,
                        want_long, want_short, InpVerboseLog, reason))
      return false;

   if(!CTS_PositionCapsOk(sym, InpMagic, InpMaxOpenTrades, InpOnePositionPerDir, InpOnePositionTotal,
                          is_long, InpVerboseLog, reason))
      return false;

   if(!SymbolInfoInteger(sym, SYMBOL_SELECT))
      SymbolSelect(sym, true);

   const double entry = is_long ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);

   double sl = 0.0, tp = 0.0;
   string e2 = "";
   if(!CTS_ComputeStops(sym, is_long, InpSLMode, InpSLPoints, InpATRMultSL, buf.atr1,
                        InpTPMode, InpTPPoints, InpTPRiskReward, entry, sl, tp, e2))
     {
      Print("CTS: stops calc failed: ", e2);
      return false;
     }

   if(!CTS_ValidateStopsDistance(sym, is_long, entry, sl, tp, e2))
     {
      CTS_LogV(InpVerboseLog, StringFormat("CTS: stops validation: %s", e2));
      return false;
     }

   double lots = InpFixedLots;
   if(InpUseRiskPercent)
     {
      if(!CTS_ComputeVolumeForRisk(sym, is_long, entry, sl, InpRiskPercent, lots, e2))
        {
         Print("CTS: volume risk failed: ", e2);
         return false;
        }
     }
     else
      {
      if(!CTS_NormalizeVolume(sym, lots))
        {
         Print("CTS: fixed volume normalize failed");
         return false;
        }
     }

   if(InpUseAiGate && InpAiApplyRiskMultiplier)
     {
      const double rm = CTS_AiGate_ConsumeRiskMultiplier();
      if(MathAbs(rm - 1.0) > 1e-6)
        {
         const double lots_before = lots;
         if(!CTS_ApplyRiskMultiplier(sym, lots, rm, InpAiRiskMultMin, InpAiRiskMultMax, e2))
           {
            PrintFormat("CTS: risk_multiplier %.3f skipped: %s (lots=%.2f)", rm, e2, lots_before);
            lots = lots_before;
           }
         else
           {
            CTS_LogV(InpVerboseLog, StringFormat("CTS: lots %.2f -> %.2f (risk_mult=%.3f)", lots_before, lots, rm));
           }
        }
     }
   else
      CTS_AiGate_ConsumeRiskMultiplier();

   string send_err = "";
   ulong deal_ticket = 0;
   int send_retcode = 0;
   if(!CTS_OpenMarket(g_trade, sym, InpMagic, InpSlippagePoints, is_long, lots, sl, tp, InpVerboseLog, send_err,
                      deal_ticket, send_retcode))
      return false;

   string exec_err = "";
   if(!CTS_LogCsv_AppendExecutionRow(InpLogCsvEnable, InpLogOrders, sym, tf, signal_id, is_long, lots, entry, sl, tp,
                                     send_retcode, deal_ticket, InpVerboseLog, exec_err))
     {
      if(StringLen(exec_err) > 0)
         Print("CTS: LogCsv execution row: ", exec_err);
     }

   CTS_State_OnEntryOpened(sym, tf);
   return true;
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   string err = "";
   if(!CTS_ValidateInputs(err))
     {
      Print("CTS OnInit failed: ", err);
      return INIT_FAILED;
     }

   const string sym = CTS_WorkSymbol();
   const ENUM_TIMEFRAMES tf = CTS_SignalTimeframe();

   if(!CTS_IndicatorsInit(sym, tf, InpEMAFast, InpEMASlow, InpMacdFast, InpMacdSlow, InpMacdSignal, InpATRPeriod, err))
     {
      Print("CTS OnInit indicators: ", err);
      return INIT_FAILED;
     }

   CTS_State_ResetBarDetector();

   string log_err = "";
   string eff_sub = InpLogCsvSubdir;
   if(MQLInfoInteger(MQL_TESTER) != 0 && InpLogInTester)
      eff_sub = InpLogTesterSubdir;
   if(!CTS_LogCsv_Week1Init(InpLogCsvEnable, InpLogCsvTestRow, eff_sub, InpLogInTester, InpLogTesterMaxRows,
                            InpLogOrders, sym, tf, InpVerboseLog, log_err))
     {
      Print("CTS: LogCsv init skipped/failed: ", log_err, " (trading continues)");
     }

   PrintFormat("CTS: initialized sym=%s tf=%s", sym, EnumToString(tf));
   if(InpUseAiGate)
     {
      if(CTS_AiGate_UseMockInTester(InpUseAiGate, InpAiMockScoreInTester))
        {
         const double mthr = (InpAiMockThresholdInTester >= 0.0) ? InpAiMockThresholdInTester : InpAiThreshold;
         PrintFormat("CTS AiGate: tester MOCK score=%.4f thr_eff=%.4f bucket=%s (no HTTP)",
                     InpAiMockScoreInTester, mthr,
                     (StringLen(InpAiMockBucketInTester) > 0) ? InpAiMockBucketInTester : "-");
        }
      else if(MQLInfoInteger(MQL_TESTER) != 0 && !InpUseAiGateInTester)
         Print("CTS AiGate: inactive in tester (set mock score 0..1 or InpUseAiGateInTester=true)");
      else
         Print("CTS AiGate: allow Tools -> Options -> Expert Advisors -> WebRequest URL http://127.0.0.1:8008");
      if(InpAiGateMode == CTS_AI_FILTER)
         PrintFormat("CTS AiGate: FILTER — skip when score < thr_eff (API per-bucket or %.4f fallback); HTTP errors skip trade", InpAiThreshold);
      else
         Print("CTS AiGate: SHADOW — bucket/thr_eff logged; trades not blocked by AI");
      if(InpAiApplyRiskMultiplier)
         PrintFormat("CTS AiGate: risk_multiplier ON — lots scaled in [%.2f, %.2f]", InpAiRiskMultMin, InpAiRiskMultMax);
     }
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   CTS_LogCsv_Close();
   CTS_IndicatorsDeinit();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   const string sym = CTS_WorkSymbol();
   const ENUM_TIMEFRAMES tf = CTS_SignalTimeframe();

   if(!CTS_IsNewBar(sym, tf))
      return;

   CTSPriceBuf buf;
   string err = "";
   if(!CTS_FetchSignalBarData(sym, tf, buf, err))
     {
      Print("CTS: data fetch: ", err);
      return;
     }

   string wl = "", ws = "";
   const bool sig_long = CTS_ShouldEnterLong(buf, wl);
   const bool sig_short = CTS_ShouldEnterShort(buf, ws);

   const bool bias_long = CTS_SignalBiasLong(buf);
   const bool bias_short = CTS_SignalBiasShort(buf);
   string skip_log = "";
   if(sig_long && sig_short)
      skip_log = "both_signals";
   else if(!sig_long && !sig_short)
      skip_log = "L:" + wl + "|S:" + ws;
   const bool would_trade = (sig_long && !sig_short) || (!sig_long && sig_short);

   const string signal_id = CTS_LogCsv_MakeSignalId(sym, tf);

   string csv_err = "";
   if(!CTS_LogCsv_AppendSignalRow(InpLogCsvEnable, InpLogSignals, sym, tf, buf,
                                  bias_long, bias_short, sig_long, sig_short, skip_log, would_trade,
                                  InpVerboseLog, csv_err))
     {
      if(StringLen(csv_err) > 0)
         Print("CTS: LogCsv append: ", csv_err);
     }

   if(sig_long && sig_short)
     {
      Print("CTS: both signals on same bar — skip");
      return;
     }

   if(sig_long)
     {
      CTS_LogV(InpVerboseLog, "CTS: LONG signal");
      string ai_log = "", ai_reason = "";
      if(!CTS_AiGate_HandleBeforeOpen(InpUseAiGate, InpUseAiGateInTester, InpAiMockScoreInTester,
                                      InpAiMockThresholdInTester, InpAiMockBucketInTester, InpAiMockRiskMultiplierInTester,
                                      CTS_AiGate_IsShadowMode(InpAiGateMode), InpAiEndpoint, InpAiTimeoutMs, InpAiThreshold,
                                      sym, tf, buf, bias_long, bias_short, sig_long, sig_short,
                                      signal_id, true, InpVerboseLog, ai_log, ai_reason))
         return;
      CTS_TryOpen(true, buf, sym, tf, signal_id);
      return;
     }

   if(sig_short)
     {
      CTS_LogV(InpVerboseLog, "CTS: SHORT signal");
      string ai_log = "", ai_reason = "";
      if(!CTS_AiGate_HandleBeforeOpen(InpUseAiGate, InpUseAiGateInTester, InpAiMockScoreInTester,
                                      InpAiMockThresholdInTester, InpAiMockBucketInTester, InpAiMockRiskMultiplierInTester,
                                      CTS_AiGate_IsShadowMode(InpAiGateMode), InpAiEndpoint, InpAiTimeoutMs, InpAiThreshold,
                                      sym, tf, buf, bias_long, bias_short, sig_long, sig_short,
                                      signal_id, false, InpVerboseLog, ai_log, ai_reason))
         return;
      CTS_TryOpen(false, buf, sym, tf, signal_id);
      return;
     }

   CTS_LogV(InpVerboseLog, StringFormat("CTS: no signal (L:%s S:%s)", wl, ws));
  }

//+------------------------------------------------------------------+

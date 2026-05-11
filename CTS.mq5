//+------------------------------------------------------------------+
//| CTS.mq5 — Classic Trend Stack execution (Phase 1)                |
//| See concept.md / roadmap.md                                      |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026"
#property link      ""
#property version   "1.01"

#include <Trade/Trade.mqh>

#include "Include/CTS_Config.mqh"
#include "Include/CTS_Log.mqh"
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

input group "Debug"
input bool              InpVerboseLog          = true;

//---
CTrade g_trade;

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
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_TryOpen(const bool is_long, const CTSPriceBuf &buf, const string sym, const ENUM_TIMEFRAMES tf)
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

   string send_err = "";
   if(!CTS_OpenMarket(g_trade, sym, InpMagic, InpSlippagePoints, is_long, lots, sl, tp, InpVerboseLog, send_err))
      return false;

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
   PrintFormat("CTS: initialized sym=%s tf=%s", sym, EnumToString(tf));
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
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

   if(sig_long && sig_short)
     {
      Print("CTS: both signals on same bar — skip");
      return;
     }

   if(sig_long)
     {
      CTS_LogV(InpVerboseLog, "CTS: LONG signal");
      CTS_TryOpen(true, buf, sym, tf);
      return;
     }

   if(sig_short)
     {
      CTS_LogV(InpVerboseLog, "CTS: SHORT signal");
      CTS_TryOpen(false, buf, sym, tf);
      return;
     }

   CTS_LogV(InpVerboseLog, StringFormat("CTS: no signal (L:%s S:%s)", wl, ws));
  }

//+------------------------------------------------------------------+

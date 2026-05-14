//+------------------------------------------------------------------+
//| CTS_Signals.mqh — closed-bar rules (concept.md)                  |
//+------------------------------------------------------------------+
#ifndef CTS_SIGNALS_MQH
#define CTS_SIGNALS_MQH

#include "CTS_Indicators.mqh"

inline bool CTS_SignalBiasLong(const CTSPriceBuf &b)
  {
   return (b.close1 > b.ema200_1) && (b.ema50_1 > b.ema200_1);
  }

inline bool CTS_SignalBiasShort(const CTSPriceBuf &b)
  {
   return (b.close1 < b.ema200_1) && (b.ema50_1 < b.ema200_1);
  }

inline bool CTS_ShouldEnterLong(const CTSPriceBuf &b, string &why_not)
  {
   why_not = "";
   if(b.close1 <= b.ema200_1)
     {
      why_not = "long: close not above EMA200";
      return false;
     }
   if(b.ema50_1 <= b.ema200_1)
     {
      why_not = "long: EMA50 not above EMA200";
      return false;
     }
   const bool ema_cross = (b.ema50_2 <= b.ema200_2) && (b.ema50_1 > b.ema200_1);
   if(!ema_cross)
     {
      why_not = "long: no bullish EMA50/200 cross on signal bar";
      return false;
     }
   const bool macd_cross = (b.macd_main2 <= b.macd_sig2) && (b.macd_main1 > b.macd_sig1);
   if(!macd_cross)
     {
      why_not = "long: no bullish MACD cross on signal bar";
      return false;
     }
   return true;
  }

inline bool CTS_ShouldEnterShort(const CTSPriceBuf &b, string &why_not)
  {
   why_not = "";
   if(b.close1 >= b.ema200_1)
     {
      why_not = "short: close not below EMA200";
      return false;
     }
   if(b.ema50_1 >= b.ema200_1)
     {
      why_not = "short: EMA50 not below EMA200";
      return false;
     }
   const bool ema_cross = (b.ema50_2 >= b.ema200_2) && (b.ema50_1 < b.ema200_1);
   if(!ema_cross)
     {
      why_not = "short: no bearish EMA50/200 cross on signal bar";
      return false;
     }
   const bool macd_cross = (b.macd_main2 >= b.macd_sig2) && (b.macd_main1 < b.macd_sig1);
   if(!macd_cross)
     {
      why_not = "short: no bearish MACD cross on signal bar";
      return false;
     }
   return true;
  }

#endif // CTS_SIGNALS_MQH

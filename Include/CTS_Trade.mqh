//+------------------------------------------------------------------+
//| CTS_Trade.mqh — guards + market send                             |
//+------------------------------------------------------------------+
#ifndef CTS_TRADE_MQH
#define CTS_TRADE_MQH

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>

#include "CTS_Config.mqh"
#include "CTS_Log.mqh"

inline int CTS_CountOurPositions(const string sym, const long magic, const int type_filter)
  {
   CPositionInfo pi;
   int count = 0;
   const int total = PositionsTotal();
   for(int i = total - 1; i >= 0; --i)
     {
      if(!pi.SelectByIndex(i))
         continue;
      if(pi.Symbol() != sym || pi.Magic() != (long)magic)
         continue;
      if(type_filter >= 0 && pi.PositionType() != type_filter)
         continue;
      ++count;
     }
   return count;
  }

inline bool CTS_GuardsCommon(const string sym,
                             const int max_spread_points,
                             const double min_equity,
                             const ENUM_CTS_TRADE_DIR dir,
                             const bool want_long,
                             const bool want_short,
                             const bool verbose,
                             string &reason)
  {
   reason = "";
   if(max_spread_points > 0)
     {
      const double spread_pts = (SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID)) /
                                SymbolInfoDouble(sym, SYMBOL_POINT);
      if(spread_pts > (double)max_spread_points)
        {
         reason = StringFormat("Spread too high: %.1f > %d", spread_pts, max_spread_points);
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
     }

   if(min_equity > 0.0)
     {
      const double eq = AccountInfoDouble(ACCOUNT_EQUITY);
      if(eq < min_equity)
        {
         reason = StringFormat("Equity below floor: %.2f < %.2f", eq, min_equity);
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
     }

   if(want_long && dir == CTS_DIR_SELL_ONLY)
     {
      reason = "Buy blocked by direction filter";
      return false;
     }
   if(want_short && dir == CTS_DIR_BUY_ONLY)
     {
      reason = "Sell blocked by direction filter";
      return false;
     }

   return true;
  }

inline bool CTS_PositionCapsOk(const string sym, const long magic,
                             const int max_open,
                             const bool one_per_dir,
                             const bool one_total,
                             const bool opening_long,
                             const bool verbose,
                             string &reason)
  {
   reason = "";
   const int buys = CTS_CountOurPositions(sym, magic, POSITION_TYPE_BUY);
   const int sells = CTS_CountOurPositions(sym, magic, POSITION_TYPE_SELL);
   const int allp = buys + sells;

   if(max_open > 0 && allp >= max_open)
     {
      reason = StringFormat("Max open trades reached: %d", max_open);
      CTS_LogV(verbose, "CTS: " + reason);
      return false;
     }

   if(one_total && allp > 0)
     {
      reason = "One total position: already open";
      CTS_LogV(verbose, "CTS: " + reason);
      return false;
     }

   if(one_per_dir)
     {
      if(opening_long && buys > 0)
        {
         reason = "One per direction: buy already open";
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
      if(!opening_long && sells > 0)
        {
         reason = "One per direction: sell already open";
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
     }

   return true;
  }

inline void CTS_SetFilling(CTrade &trade, const string sym)
  {
   const long mask = (long)SymbolInfoInteger(sym, SYMBOL_FILLING_MODE);
   if((mask & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK)
      trade.SetTypeFilling(ORDER_FILLING_FOK);
   else if((mask & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC)
      trade.SetTypeFilling(ORDER_FILLING_IOC);
   else
      trade.SetTypeFilling(ORDER_FILLING_RETURN);
  }

inline bool CTS_OpenMarket(CTrade &trade, const string sym, const long magic,
                           const int deviation_points,
                           const bool is_buy,
                           const double volume,
                           const double sl, const double tp,
                           const bool verbose,
                           string &err)
  {
   err = "";
   trade.SetExpertMagicNumber((ulong)magic);
   trade.SetDeviationInPoints(deviation_points);
   CTS_SetFilling(trade, sym);

   const bool ok = is_buy
                   ? trade.Buy(volume, sym, 0.0, sl, tp, "CTS")
                   : trade.Sell(volume, sym, 0.0, sl, tp, "CTS");

   if(!ok)
     {
      err = StringFormat("OrderSend failed: retcode=%d %s",
                         (int)trade.ResultRetcode(), trade.ResultRetcodeDescription());
      Print("CTS: ", err);
      return false;
     }

   CTS_LogV(verbose, StringFormat("CTS: %s opened vol=%.2f SL=%.5f TP=%.5f",
                                  is_buy ? "BUY" : "SELL", volume, sl, tp));
   return true;
  }

#endif // CTS_TRADE_MQH

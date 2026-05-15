//+------------------------------------------------------------------+
//| CTS_Risk.mqh — volume, SL/TP price levels                        |
//+------------------------------------------------------------------+
#ifndef CTS_RISK_MQH
#define CTS_RISK_MQH

#include "CTS_Config.mqh"

inline bool CTS_NormalizeVolume(const string sym, double &lots)
  {
   const double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   const double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   const double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0.0 || vmin <= 0.0 || vmax <= 0.0)
      return false;
   lots = MathFloor(lots / step + 1e-12) * step;
   if(lots < vmin - 1e-12)
      return false;
   if(lots > vmax)
      lots = vmax;
   return true;
  }

inline bool CTS_ComputeVolumeForRisk(const string sym, const bool is_buy,
                                     const double entry_price, const double sl_price,
                                     const double risk_percent_equity,
                                     double &lots_out, string &err)
  {
   err = "";
   lots_out = 0.0;
   if(risk_percent_equity <= 0.0)
     {
      err = "Risk percent must be > 0";
      return false;
     }

   const ENUM_ORDER_TYPE ot = is_buy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double profit_at_sl = 0.0;
   if(!OrderCalcProfit(ot, sym, 1.0, entry_price, sl_price, profit_at_sl))
     {
      err = "OrderCalcProfit failed";
      return false;
     }
   const double loss_per_lot = MathAbs(profit_at_sl);
   if(loss_per_lot < 1e-8)
     {
      err = "SL too close to entry for risk sizing";
      return false;
     }

   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const double risk_money = equity * (risk_percent_equity / 100.0);
   if(risk_money <= 0.0)
     {
      err = "Equity or risk money invalid";
      return false;
     }

   lots_out = risk_money / loss_per_lot;
   if(!CTS_NormalizeVolume(sym, lots_out))
     {
      err = "Normalized volume below broker minimum";
      return false;
     }
   return true;
  }

// Phase 5 — scale lots by adaptive risk_multiplier (clamped), then broker normalize.
inline bool CTS_ApplyRiskMultiplier(const string sym, double &lots,
                                    const double risk_multiplier,
                                    const double mult_min,
                                    const double mult_max,
                                    string &err)
  {
   err = "";
   if(risk_multiplier <= 0.0)
     {
      err = "risk_multiplier must be > 0";
      return false;
     }
   double m = risk_multiplier;
   if(mult_min > 0.0 && m < mult_min)
      m = mult_min;
   if(mult_max > 0.0 && m > mult_max)
      m = mult_max;
   lots *= m;
   if(!CTS_NormalizeVolume(sym, lots))
     {
      err = "volume below minimum after risk_multiplier";
      return false;
     }
   return true;
  }

inline bool CTS_ComputeStops(const string sym, const bool is_buy,
                             const ENUM_CTS_SL_MODE sl_mode,
                             const int sl_points,
                             const double atr_mult,
                             const double atr_value_bar1,
                             const ENUM_CTS_TP_MODE tp_mode,
                             const int tp_points,
                             const double tp_rr,
                             const double entry_price,
                             double &sl_price, double &tp_price,
                             string &err)
  {
   err = "";
   const double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(point <= 0.0)
     {
      err = "Invalid SYMBOL_POINT";
      return false;
     }

   double sl_dist = 0.0;
   if(sl_mode == CTS_SL_FIXED)
     {
      if(sl_points <= 0)
        {
         err = "SL points must be > 0 in fixed mode";
         return false;
        }
      sl_dist = sl_points * point;
     }
   else
     {
      if(atr_value_bar1 <= 0.0 || atr_mult <= 0.0)
        {
         err = "ATR SL: invalid ATR or multiplier";
         return false;
        }
      sl_dist = atr_value_bar1 * atr_mult;
     }

   if(sl_dist <= 0.0)
     {
      err = "SL distance invalid";
      return false;
     }

   if(is_buy)
     {
      sl_price = entry_price - sl_dist;
      if(tp_mode == CTS_TP_FIXED)
        {
         if(tp_points <= 0)
           {
            err = "TP points must be > 0 in fixed TP mode";
            return false;
           }
         tp_price = entry_price + (tp_points * point);
        }
      else
        {
         if(tp_rr <= 0.0)
           {
            err = "TP RR must be > 0";
            return false;
           }
         tp_price = entry_price + sl_dist * tp_rr;
        }
     }
   else
     {
      sl_price = entry_price + sl_dist;
      if(tp_mode == CTS_TP_FIXED)
        {
         if(tp_points <= 0)
           {
            err = "TP points must be > 0 in fixed TP mode";
            return false;
           }
         tp_price = entry_price - (tp_points * point);
        }
      else
        {
         if(tp_rr <= 0.0)
           {
            err = "TP RR must be > 0";
            return false;
           }
         tp_price = entry_price - sl_dist * tp_rr;
        }
     }

   return true;
  }

inline bool CTS_ValidateStopsDistance(const string sym, const bool is_buy,
                                      const double entry_price,
                                      const double sl_price, const double tp_price,
                                      string &err)
  {
   err = "";
   const int stops_level = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   const double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(point <= 0.0)
     {
      err = "Invalid point";
      return false;
     }
   const double freeze = (double)SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL) * point;

   if(is_buy)
     {
      if(sl_price >= entry_price)
        {
         err = "Buy: SL must be below entry";
         return false;
        }
      if(tp_price <= entry_price)
        {
         err = "Buy: TP must be above entry";
         return false;
        }
      if((entry_price - sl_price) < stops_level * point - 1e-8)
        {
         err = "Buy: SL inside stops level";
         return false;
        }
      if((tp_price - entry_price) < stops_level * point - 1e-8)
        {
         err = "Buy: TP inside stops level";
         return false;
        }
     }
   else
     {
      if(sl_price <= entry_price)
        {
         err = "Sell: SL must be above entry";
         return false;
        }
      if(tp_price >= entry_price)
        {
         err = "Sell: TP must be below entry";
         return false;
        }
      if((sl_price - entry_price) < stops_level * point - 1e-8)
        {
         err = "Sell: SL inside stops level";
         return false;
        }
      if((entry_price - tp_price) < stops_level * point - 1e-8)
        {
         err = "Sell: TP inside stops level";
         return false;
        }
     }

   if(freeze > 0.0)
     {
      // Minimal sanity: prices not inside freeze band vs bid/ask is broker-specific; stops_level is primary.
     }

   return true;
  }

#endif // CTS_RISK_MQH

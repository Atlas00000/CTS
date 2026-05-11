//+------------------------------------------------------------------+
//| CTS_State.mqh — new bar + cooldown memory                        |
//+------------------------------------------------------------------+
#ifndef CTS_STATE_MQH
#define CTS_STATE_MQH

#include "CTS_Log.mqh"

static datetime g_cts_last_bar0_time = 0;
static datetime g_cts_last_entry_signal_bar_time = 0;
static datetime g_cts_last_entry_wallclock = 0;

inline bool CTS_IsNewBar(const string sym, const ENUM_TIMEFRAMES tf)
  {
   const datetime t0 = iTime(sym, tf, 0);
   if(t0 == 0)
      return false;
   if(t0 == g_cts_last_bar0_time)
      return false;
   g_cts_last_bar0_time = t0;
   return true;
  }

inline void CTS_State_ResetBarDetector()
  {
   g_cts_last_bar0_time = 0;
  }

inline void CTS_State_OnEntryOpened(const string sym, const ENUM_TIMEFRAMES tf)
  {
   g_cts_last_entry_signal_bar_time = iTime(sym, tf, 1);
   g_cts_last_entry_wallclock = TimeCurrent();
  }

inline bool CTS_CooldownOk(const string sym, const ENUM_TIMEFRAMES tf,
                           const int cooldown_bars, const int cooldown_minutes,
                           const bool verbose, string &reason)
  {
   reason = "";
   if(g_cts_last_entry_signal_bar_time == 0 && g_cts_last_entry_wallclock == 0)
      return true;

   if(cooldown_bars > 0 && g_cts_last_entry_signal_bar_time != 0)
     {
      const int sh_last = iBarShift(sym, tf, g_cts_last_entry_signal_bar_time, true);
      if(sh_last < 0)
        {
         reason = "Cooldown: cannot resolve last entry bar";
         return false;
        }
      const int bars_since = sh_last - 1;
      if(bars_since < cooldown_bars)
        {
         reason = StringFormat("Cooldown bars: need %d, have %d", cooldown_bars, bars_since);
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
     }

   if(cooldown_minutes > 0 && g_cts_last_entry_wallclock != 0)
     {
      const int need = cooldown_minutes * 60;
      if((TimeCurrent() - g_cts_last_entry_wallclock) < need)
        {
         reason = StringFormat("Cooldown minutes: need %d", cooldown_minutes);
         CTS_LogV(verbose, "CTS: " + reason);
         return false;
        }
     }

   return true;
  }

#endif // CTS_STATE_MQH

//+------------------------------------------------------------------+
//| CTS_Log.mqh                                                      |
//+------------------------------------------------------------------+
#ifndef CTS_LOG_MQH
#define CTS_LOG_MQH

inline void CTS_LogV(const bool verbose, const string msg)
  {
   if(verbose)
      Print(msg);
  }

#endif // CTS_LOG_MQH

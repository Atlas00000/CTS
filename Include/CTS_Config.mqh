//+------------------------------------------------------------------+
//| CTS_Config.mqh                                                   |
//+------------------------------------------------------------------+
#ifndef CTS_CONFIG_MQH
#define CTS_CONFIG_MQH

enum ENUM_CTS_TRADE_DIR
  {
   CTS_DIR_BOTH = 0,
   CTS_DIR_BUY_ONLY,
   CTS_DIR_SELL_ONLY
  };

enum ENUM_CTS_SL_MODE
  {
   CTS_SL_FIXED = 0,
   CTS_SL_ATR
  };

enum ENUM_CTS_TP_MODE
  {
   CTS_TP_FIXED = 0,
   CTS_TP_RR
  };

#endif // CTS_CONFIG_MQH

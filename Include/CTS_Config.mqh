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

// Phase 4 — labels appear in Strategy Tester dropdown (keep short)
enum ENUM_CTS_AI_GATE_MODE
  {
   CTS_AI_SHADOW = 0,   // SHADOW — log only
   CTS_AI_FILTER = 1    // FILTER — block trades
  };

#endif // CTS_CONFIG_MQH

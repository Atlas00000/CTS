//+------------------------------------------------------------------+
//| CTS_Indicators.mqh                                               |
//+------------------------------------------------------------------+
#ifndef CTS_INDICATORS_MQH
#define CTS_INDICATORS_MQH

static int g_cts_h_ema50 = INVALID_HANDLE;
static int g_cts_h_ema200 = INVALID_HANDLE;
static int g_cts_h_macd = INVALID_HANDLE;
static int g_cts_h_atr = INVALID_HANDLE;

struct CTSPriceBuf
  {
   double            close1;
   double            ema50_1, ema50_2;
   double            ema200_1, ema200_2;
   double            macd_main1, macd_main2;
   double            macd_sig1, macd_sig2;
   double            atr1;
  };

inline bool CTS_IndicatorsInit(const string sym, const ENUM_TIMEFRAMES tf,
                               const int ema_fast, const int ema_slow,
                               const int macd_fast, const int macd_slow, const int macd_signal,
                               const int atr_period,
                               string &err)
  {
   err = "";
   CTS_IndicatorsDeinit();

   g_cts_h_ema50 = iMA(sym, tf, ema_fast, 0, MODE_EMA, PRICE_CLOSE);
   g_cts_h_ema200 = iMA(sym, tf, ema_slow, 0, MODE_EMA, PRICE_CLOSE);
   g_cts_h_macd = iMACD(sym, tf, macd_fast, macd_slow, macd_signal, PRICE_CLOSE);
   g_cts_h_atr = iATR(sym, tf, atr_period);

   if(g_cts_h_ema50 == INVALID_HANDLE || g_cts_h_ema200 == INVALID_HANDLE ||
      g_cts_h_macd == INVALID_HANDLE || g_cts_h_atr == INVALID_HANDLE)
     {
      err = "Failed to create indicator handle(s)";
      CTS_IndicatorsDeinit();
      return false;
     }

   return true;
  }

inline void CTS_IndicatorsDeinit()
  {
   if(g_cts_h_ema50 != INVALID_HANDLE)
     {
      IndicatorRelease(g_cts_h_ema50);
      g_cts_h_ema50 = INVALID_HANDLE;
     }
   if(g_cts_h_ema200 != INVALID_HANDLE)
     {
      IndicatorRelease(g_cts_h_ema200);
      g_cts_h_ema200 = INVALID_HANDLE;
     }
   if(g_cts_h_macd != INVALID_HANDLE)
     {
      IndicatorRelease(g_cts_h_macd);
      g_cts_h_macd = INVALID_HANDLE;
     }
   if(g_cts_h_atr != INVALID_HANDLE)
     {
      IndicatorRelease(g_cts_h_atr);
      g_cts_h_atr = INVALID_HANDLE;
     }
  }

inline bool CTS_FetchSignalBarData(const string sym, const ENUM_TIMEFRAMES tf,
                                   CTSPriceBuf &b, string &err)
  {
   err = "";
   double c[];
   ArraySetAsSeries(c, true);
   if(CopyClose(sym, tf, 0, 5, c) < 5)
     {
      err = "CopyClose failed";
      return false;
     }
   b.close1 = c[1];

   double e50[];
   double e200[];
   ArraySetAsSeries(e50, true);
   ArraySetAsSeries(e200, true);
   if(CopyBuffer(g_cts_h_ema50, 0, 0, 5, e50) < 5 ||
      CopyBuffer(g_cts_h_ema200, 0, 0, 5, e200) < 5)
     {
      err = "CopyBuffer EMA failed";
      return false;
     }
   b.ema50_1 = e50[1];
   b.ema50_2 = e50[2];
   b.ema200_1 = e200[1];
   b.ema200_2 = e200[2];

   double m0[], m1[];
   ArraySetAsSeries(m0, true);
   ArraySetAsSeries(m1, true);
   if(CopyBuffer(g_cts_h_macd, 0, 0, 5, m0) < 5 ||
      CopyBuffer(g_cts_h_macd, 1, 0, 5, m1) < 5)
     {
      err = "CopyBuffer MACD failed";
      return false;
     }
   b.macd_main1 = m0[1];
   b.macd_main2 = m0[2];
   b.macd_sig1 = m1[1];
   b.macd_sig2 = m1[2];

   double a[];
   ArraySetAsSeries(a, true);
   if(CopyBuffer(g_cts_h_atr, 0, 0, 3, a) < 3)
     {
      err = "CopyBuffer ATR failed";
      return false;
     }
   b.atr1 = a[1];

   return true;
  }

#endif // CTS_INDICATORS_MQH

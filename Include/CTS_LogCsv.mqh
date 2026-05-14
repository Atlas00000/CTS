//+------------------------------------------------------------------+
//| CTS_LogCsv.mqh — Phase 2 signal + execution CSV (Week 1–3)      |
//| Contract: AI_integration.md §11                                  |
//+------------------------------------------------------------------+
#ifndef CTS_LOG_CSV_MQH
#define CTS_LOG_CSV_MQH

#include "CTS_Log.mqh"
#include "CTS_Indicators.mqh"

#define CTS_LOG_CSV_SCHEMA_VERSION 1

static int             g_cts_csv_handle = INVALID_HANDLE;
static string          g_cts_csv_open_day = "";
static bool            g_cts_csv_active = false;
static string          g_cts_log_rel_subdir = "";

static int             g_cts_csv_exec_handle = INVALID_HANDLE;
static string          g_cts_csv_exec_open_day = "";
static bool            g_cts_csv_exec_active = false;

static bool            g_cts_csv_log_in_tester = false;
static int             g_cts_csv_tester_max_rows = 0;
static bool            g_cts_csv_log_orders = false;
static int             g_cts_csv_tester_rows_written = 0;

//+------------------------------------------------------------------+
string CTS_LogCsv_FormatUtcIsoZ(const datetime t)
  {
   MqlDateTime dt;
   TimeToStruct(t, dt);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                         dt.year, dt.mon, dt.day, dt.hour, dt.min, dt.sec);
  }

//+------------------------------------------------------------------+
string CTS_LogCsv_UtcDayStr(void)
  {
   const datetime gmt = TimeGMT();
   MqlDateTime dt;
   TimeToStruct(gmt, dt);
   return StringFormat("%04d-%02d-%02d", dt.year, dt.mon, dt.day);
  }

//+------------------------------------------------------------------+
string CTS_LogCsv_MakeSignalId(const string work_sym, const ENUM_TIMEFRAMES work_tf)
  {
   const datetime bar_time = iTime(work_sym, work_tf, 1);
   const string bar_s = IntegerToString((long)bar_time);
   return work_sym + "_" + EnumToString(work_tf) + "_" + bar_s;
  }

//+------------------------------------------------------------------+
string CTS_LogCsv_SignalsHeaderLine(void)
  {
   return "schema_version,ts_gmt,symbol,tf,bar_time,open1,high1,low1,close1,"
          "ema_fast_1,ema_slow_1,macd_main1,macd_sig1,atr1,spread_points,"
          "bias_long,bias_short,sig_long,sig_short,skip_reason,would_trade,signal_id";
  }

//+------------------------------------------------------------------+
string CTS_LogCsv_ExecutionsHeaderLine(void)
  {
   return "schema_version,ts_gmt,signal_id,symbol,tf,side,volume,sl,tp,retcode,deal_ticket,deal_time_gmt";
  }

//+------------------------------------------------------------------+
string CTS_LogCsv_EscapeCommas(const string s)
  {
   string o = s;
   if(StringLen(o) > 400)
      o = StringSubstr(o, 0, 400);
   StringReplace(o, ",", ";");
   StringReplace(o, "\r", " ");
   StringReplace(o, "\n", " ");
   return o;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_SanitizeSubdir(string &sub, string &err)
  {
   err = "";
   StringTrimLeft(sub);
   StringTrimRight(sub);
   if(StringLen(sub) == 0)
      sub = "CTS_logs";
   if(StringFind(sub, "..") >= 0)
     {
      err = "Log CSV: subdir must not contain ..";
      return false;
     }
   if(StringFind(sub, "\\") >= 0 || StringFind(sub, "/") >= 0)
     {
      err = "Log CSV: subdir must be single folder name (no path separators)";
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_CsvLoggingSuppressed(void)
  {
   if(MQLInfoInteger(MQL_TESTER) != 0 && !g_cts_csv_log_in_tester)
      return true;
   return false;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_TesterCapReached(void)
  {
   if(MQLInfoInteger(MQL_TESTER) == 0)
      return false;
   if(g_cts_csv_tester_max_rows <= 0)
      return false;
   return g_cts_csv_tester_rows_written >= g_cts_csv_tester_max_rows;
  }

//+------------------------------------------------------------------+
void CTS_LogCsv_TesterNoteRow(void)
  {
   if(MQLInfoInteger(MQL_TESTER) != 0 && g_cts_csv_tester_max_rows > 0)
      g_cts_csv_tester_rows_written++;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_OpenFlagsCore(const string fname, int &out_handle, string &err)
  {
   err = "";
   const int flags = (int)FILE_READ | (int)FILE_WRITE | (int)FILE_TXT | (int)FILE_ANSI;
   out_handle = FileOpen(fname, flags);
   if(out_handle != INVALID_HANDLE)
      return true;
   err = StringFormat("Log CSV: FileOpen failed (%d): %s", GetLastError(), fname);
   return false;
  }

//+------------------------------------------------------------------+
void CTS_LogCsv_HardCloseHandle(void)
  {
   if(g_cts_csv_handle != INVALID_HANDLE)
     {
      FileFlush(g_cts_csv_handle);
      FileClose(g_cts_csv_handle);
      g_cts_csv_handle = INVALID_HANDLE;
     }
   g_cts_csv_open_day = "";
   g_cts_csv_active = false;
  }

//+------------------------------------------------------------------+
void CTS_LogCsv_HardCloseExecHandle(void)
  {
   if(g_cts_csv_exec_handle != INVALID_HANDLE)
     {
      FileFlush(g_cts_csv_exec_handle);
      FileClose(g_cts_csv_exec_handle);
      g_cts_csv_exec_handle = INVALID_HANDLE;
     }
   g_cts_csv_exec_open_day = "";
   g_cts_csv_exec_active = false;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_OpenExecutionDayFile(const string sub,
                                     const string day,
                                     const bool verbose,
                                     string &err)
  {
   err = "";
   CTS_LogCsv_HardCloseExecHandle();

   const string fname = sub + "\\CTS_EXECUTIONS_" + day + ".csv";
   if(!CTS_LogCsv_OpenFlagsCore(fname, g_cts_csv_exec_handle, err))
      return false;

   g_cts_csv_exec_open_day = day;

   const ulong sz = FileSize(g_cts_csv_exec_handle);
   if(sz == 0)
     {
      if(FileWriteString(g_cts_csv_exec_handle, CTS_LogCsv_ExecutionsHeaderLine() + "\n") == 0)
        {
         err = "Log CSV: exec header write failed";
         CTS_LogCsv_HardCloseExecHandle();
         return false;
        }
      FileFlush(g_cts_csv_exec_handle);
     }
   else
     {
      if(FileSeek(g_cts_csv_exec_handle, 0, SEEK_END) == false)
        {
         err = "Log CSV: exec FileSeek failed";
         CTS_LogCsv_HardCloseExecHandle();
         return false;
        }
     }

   g_cts_csv_exec_active = true;
   CTS_LogV(verbose, StringFormat("CTS LogCsv: opened %s", fname));
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_OpenDayFile(const string sub,
                            const string day,
                            const bool write_test_row,
                            const string work_sym,
                            const ENUM_TIMEFRAMES work_tf,
                            const bool verbose,
                            string &err)
  {
   err = "";
   CTS_LogCsv_HardCloseHandle();
   CTS_LogCsv_HardCloseExecHandle();

   const string fname = sub + "\\CTS_SIGNALS_" + day + ".csv";
   if(!CTS_LogCsv_OpenFlagsCore(fname, g_cts_csv_handle, err))
      return false;

   g_cts_csv_open_day = day;

   const ulong sz = FileSize(g_cts_csv_handle);
   if(sz == 0)
     {
      if(FileWriteString(g_cts_csv_handle, CTS_LogCsv_SignalsHeaderLine() + "\n") == 0)
        {
         err = "Log CSV: failed writing header";
         CTS_LogCsv_HardCloseHandle();
         return false;
        }
      if(write_test_row)
        {
         const string ts = CTS_LogCsv_FormatUtcIsoZ(TimeGMT());
         const string sid = "WEEK1_INIT_" + work_sym + "_" + day;
         // bar_time + OHLC(4) + ema(2) + macd(2) + atr + spread_points = 11 numeric fields before booleans
         const string row = StringFormat(
                               "%d,%s,%s,%s,0,0,0,0,0,0,0,0,0,0,0,false,false,false,false,week1_init,false,%s\n",
                               CTS_LOG_CSV_SCHEMA_VERSION, ts, work_sym, EnumToString(work_tf), sid);
         if(FileWriteString(g_cts_csv_handle, row) == 0)
           {
            err = "Log CSV: failed writing test row";
            CTS_LogCsv_HardCloseHandle();
            return false;
           }
        }
      FileFlush(g_cts_csv_handle);
     }
   else
     {
      if(FileSeek(g_cts_csv_handle, 0, SEEK_END) == false)
        {
         err = "Log CSV: FileSeek SEEK_END failed";
         CTS_LogCsv_HardCloseHandle();
         return false;
        }
     }

   g_cts_csv_active = true;
   CTS_LogV(verbose, StringFormat("CTS LogCsv: opened %s", fname));

   if(g_cts_csv_log_orders && !CTS_LogCsv_CsvLoggingSuppressed())
     {
      string e2 = "";
      if(!CTS_LogCsv_OpenExecutionDayFile(sub, day, verbose, e2))
         CTS_LogV(verbose, "CTS LogCsv: exec file not opened: " + e2);
     }

   return true;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_Week1Init(const bool master_enabled,
                          const bool write_test_row,
                          const string effective_subdir_in,
                          const bool log_in_tester,
                          const int tester_max_rows,
                          const bool log_orders,
                          const string work_sym,
                          const ENUM_TIMEFRAMES work_tf,
                          const bool verbose,
                          string &err)
  {
   err = "";
   g_cts_log_rel_subdir = "";
   g_cts_csv_log_in_tester = log_in_tester;
   g_cts_csv_tester_max_rows = tester_max_rows;
   g_cts_csv_log_orders = log_orders;
   g_cts_csv_tester_rows_written = 0;
   CTS_LogCsv_HardCloseHandle();
   CTS_LogCsv_HardCloseExecHandle();

   if(!master_enabled)
      return true;

   if(CTS_LogCsv_CsvLoggingSuppressed())
      return true;

   string sub = effective_subdir_in;
   if(!CTS_LogCsv_SanitizeSubdir(sub, err))
      return false;

   ResetLastError();
   FolderCreate(sub);

   g_cts_log_rel_subdir = sub;
   const string day = CTS_LogCsv_UtcDayStr();
   if(!CTS_LogCsv_OpenDayFile(sub, day, write_test_row, work_sym, work_tf, verbose, err))
     {
      g_cts_log_rel_subdir = "";
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_AppendSignalRow(const bool master_enabled,
                                const bool log_signals,
                                const string work_sym,
                                const ENUM_TIMEFRAMES work_tf,
                                const CTSPriceBuf &buf,
                                const bool bias_long,
                                const bool bias_short,
                                const bool sig_long,
                                const bool sig_short,
                                const string skip_reason_raw,
                                const bool would_trade,
                                const bool verbose,
                                string &err)
  {
   err = "";
   if(CTS_LogCsv_CsvLoggingSuppressed())
      return true;
   if(!master_enabled || !log_signals)
      return true;
   if(CTS_LogCsv_TesterCapReached())
      return true;
   if(!g_cts_csv_active || StringLen(g_cts_log_rel_subdir) == 0)
      return true;

   const string today = CTS_LogCsv_UtcDayStr();
   if(today != g_cts_csv_open_day)
     {
      if(!CTS_LogCsv_OpenDayFile(g_cts_log_rel_subdir, today, false, work_sym, work_tf, verbose, err))
         return false;
     }

   const datetime bar_time = iTime(work_sym, work_tf, 1);
   const string bar_s = IntegerToString((long)bar_time);
   const string signal_id = CTS_LogCsv_MakeSignalId(work_sym, work_tf);

   const double point = SymbolInfoDouble(work_sym, SYMBOL_POINT);
   double spread_pts = 0.0;
   if(point > 0.0)
      spread_pts = (SymbolInfoDouble(work_sym, SYMBOL_ASK) - SymbolInfoDouble(work_sym, SYMBOL_BID)) / point;

   const string ts = CTS_LogCsv_FormatUtcIsoZ(TimeGMT());
   const string skip_esc = CTS_LogCsv_EscapeCommas(skip_reason_raw);
   const int dig = (int)SymbolInfoInteger(work_sym, SYMBOL_DIGITS);
   const string row = StringFormat(
                         "%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n",
                         CTS_LOG_CSV_SCHEMA_VERSION,
                         ts,
                         work_sym,
                         EnumToString(work_tf),
                         bar_s,
                         DoubleToString(buf.open1, dig),
                         DoubleToString(buf.high1, dig),
                         DoubleToString(buf.low1, dig),
                         DoubleToString(buf.close1, dig),
                         DoubleToString(buf.ema50_1, 8),
                         DoubleToString(buf.ema200_1, 8),
                         DoubleToString(buf.macd_main1, 8),
                         DoubleToString(buf.macd_sig1, 8),
                         DoubleToString(buf.atr1, 8),
                         DoubleToString(spread_pts, 1),
                         bias_long ? "true" : "false",
                         bias_short ? "true" : "false",
                         sig_long ? "true" : "false",
                         sig_short ? "true" : "false",
                         skip_esc,
                         would_trade ? "true" : "false",
                         signal_id);

   if(FileWriteString(g_cts_csv_handle, row) == 0)
     {
      err = "Log CSV: FileWriteString failed";
      return false;
     }
   FileFlush(g_cts_csv_handle);
   CTS_LogCsv_TesterNoteRow();
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_AppendExecutionRow(const bool master_enabled,
                                   const bool log_orders,
                                   const string work_sym,
                                   const ENUM_TIMEFRAMES work_tf,
                                   const string signal_id,
                                   const bool is_buy,
                                   const double volume,
                                   const double sl,
                                   const double tp,
                                   const int retcode,
                                   const ulong deal_ticket,
                                   const bool verbose,
                                   string &err)
  {
   err = "";
   if(CTS_LogCsv_CsvLoggingSuppressed())
      return true;
   if(!master_enabled || !log_orders)
      return true;
   if(CTS_LogCsv_TesterCapReached())
      return true;
   if(!g_cts_csv_exec_active || g_cts_csv_exec_handle == INVALID_HANDLE)
      return true;

   const string today = CTS_LogCsv_UtcDayStr();
   if(today != g_cts_csv_exec_open_day)
     {
      if(!CTS_LogCsv_OpenExecutionDayFile(g_cts_log_rel_subdir, today, verbose, err))
         return false;
     }

   const string ts = CTS_LogCsv_FormatUtcIsoZ(TimeGMT());
   const int dig = (int)SymbolInfoInteger(work_sym, SYMBOL_DIGITS);
   const string side = is_buy ? "BUY" : "SELL";
   const string row = StringFormat(
                         "%d,%s,%s,%s,%s,%s,%s,%s,%s,%d,%s,%s\n",
                         CTS_LOG_CSV_SCHEMA_VERSION,
                         ts,
                         signal_id,
                         work_sym,
                         EnumToString(work_tf),
                         side,
                         DoubleToString(volume, 2),
                         DoubleToString(sl, dig),
                         DoubleToString(tp, dig),
                         retcode,
                         IntegerToString((long)deal_ticket),
                         ts);

   if(FileWriteString(g_cts_csv_exec_handle, row) == 0)
     {
      err = "Log CSV: exec FileWriteString failed";
      return false;
     }
   FileFlush(g_cts_csv_exec_handle);
   CTS_LogCsv_TesterNoteRow();
   return true;
  }

//+------------------------------------------------------------------+
void CTS_LogCsv_Close(void)
  {
   CTS_LogCsv_HardCloseHandle();
   CTS_LogCsv_HardCloseExecHandle();
   g_cts_log_rel_subdir = "";
   g_cts_csv_tester_rows_written = 0;
  }

//+------------------------------------------------------------------+
bool CTS_LogCsv_IsActive(void)
  {
   return g_cts_csv_active;
  }

#endif // CTS_LOG_CSV_MQH

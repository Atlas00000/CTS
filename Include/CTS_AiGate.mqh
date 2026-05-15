//+------------------------------------------------------------------+
//| CTS_AiGate.mqh — Phase 4 Week 3: local AI score via WebRequest   |
//| Shadow: log score/threshold/would_allow; do not block TryOpen.   |
//| Filter (Week 4): block when score < threshold; fail-safe on error.|
//+------------------------------------------------------------------+
#ifndef CTS_AI_GATE_MQH
#define CTS_AI_GATE_MQH

#include "CTS_Indicators.mqh"
#include "CTS_Log.mqh"

struct CTSAiScoreResult
  {
   bool              ok;
   double            score;
   double            threshold;
   bool              would_allow;
   int               http_status;
   int               web_retcode;
   string            err;
  };

//+------------------------------------------------------------------+
bool CTS_AiGate_IsActive(const bool use_ai_gate,
                         const bool allow_in_tester,
                         const bool verbose)
  {
   if(!use_ai_gate)
      return false;
   if(MQLInfoInteger(MQL_TESTER) != 0 && !allow_in_tester)
     {
      CTS_LogV(verbose, "CTS AiGate: disabled in Strategy Tester (InpUseAiGateInTester=false)");
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_DLLS_ALLOWED))
     {
      CTS_LogV(verbose, "CTS AiGate: TERMINAL_DLLS_ALLOWED is false — enable algo trading / DLL");
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_ValidateEndpoint(const string endpoint, string &err)
  {
   err = "";
   string u = endpoint;
   StringTrimLeft(u);
   StringTrimRight(u);
   if(StringLen(u) < 12)
     {
      err = "AiGate endpoint too short";
      return false;
     }
   if(StringFind(u, "http://127.0.0.1") != 0 && StringFind(u, "http://localhost") != 0)
     {
      err = "AiGate endpoint must start with http://127.0.0.1 or http://localhost";
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
double CTS_AiGate_SpreadPoints(const string sym)
  {
   const double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(point <= 0.0)
      return 0.0;
   return (SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID)) / point;
  }

//+------------------------------------------------------------------+
string CTS_AiGate_JsonEscape(const string s)
  {
   string o = s;
   StringReplace(o, "\\", "\\\\");
   StringReplace(o, "\"", "\\\"");
   return o;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_BuildFeatureJson(const string sym,
                                 const ENUM_TIMEFRAMES tf,
                                 const CTSPriceBuf &buf,
                                 const bool bias_long,
                                 const bool bias_short,
                                 const bool sig_long,
                                 const bool sig_short,
                                 string &json_out)
  {
   const datetime bar_time = iTime(sym, tf, 1);
   const int dig = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   const double spread_pts = CTS_AiGate_SpreadPoints(sym);

   const string bar_s = IntegerToString((long)bar_time);
   json_out = StringFormat(
                  "{"
                  "\"bar_time\":%s,"
                  "\"open1\":%s,"
                  "\"high1\":%s,"
                  "\"low1\":%s,"
                  "\"close1\":%s,"
                  "\"ema_fast_1\":%.8f,"
                  "\"ema_slow_1\":%.8f,"
                  "\"macd_main1\":%.8f,"
                  "\"macd_sig1\":%.8f,"
                  "\"atr1\":%.8f,"
                  "\"spread_points\":%.1f,"
                  "\"bias_long\":%s,"
                  "\"bias_short\":%s,"
                  "\"sig_long\":%s,"
                  "\"sig_short\":%s,"
                  "\"symbol\":\"%s\","
                  "\"tf\":\"%s\""
                  "}",
                  bar_s,
                  DoubleToString(buf.open1, dig),
                  DoubleToString(buf.high1, dig),
                  DoubleToString(buf.low1, dig),
                  DoubleToString(buf.close1, dig),
                  buf.ema50_1,
                  buf.ema200_1,
                  buf.macd_main1,
                  buf.macd_sig1,
                  buf.atr1,
                  spread_pts,
                  bias_long ? "true" : "false",
                  bias_short ? "true" : "false",
                  sig_long ? "true" : "false",
                  sig_short ? "true" : "false",
                  CTS_AiGate_JsonEscape(sym),
                  CTS_AiGate_JsonEscape(EnumToString(tf)));
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_ParseJsonDouble(const string body, const string key, double &out_val)
  {
   const string needle = "\"" + key + "\":";
   int pos = StringFind(body, needle);
   if(pos < 0)
      return false;
   pos += StringLen(needle);
   int end = StringFind(body, ",", pos);
   if(end < 0)
      end = StringFind(body, "}", pos);
   if(end < 0)
      return false;
   string chunk = StringSubstr(body, pos, end - pos);
   StringTrimLeft(chunk);
   StringTrimRight(chunk);
   out_val = StringToDouble(chunk);
   return true;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_ParseJsonBool(const string body, const string key, bool &out_val)
  {
   const string needle = "\"" + key + "\":";
   int pos = StringFind(body, needle);
   if(pos < 0)
      return false;
   pos += StringLen(needle);
   if(StringSubstr(body, pos, 4) == "true")
     {
      out_val = true;
      return true;
     }
   if(StringSubstr(body, pos, 5) == "false")
     {
      out_val = false;
      return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_QueryScore(const string endpoint,
                           const int timeout_ms,
                           const string json_body,
                           const bool verbose,
                           CTSAiScoreResult &out)
  {
   out.ok = false;
   out.score = 0.0;
   out.threshold = 0.0;
   out.would_allow = false;
   out.http_status = -1;
   out.web_retcode = -1;
   out.err = "";

   uchar post[];
   uchar result[];
   string result_headers = "";
   const int n = StringToCharArray(json_body, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(n <= 0)
     {
      out.err = "StringToCharArray failed";
      return false;
     }
   ArrayResize(post, n - 1);

   const string headers = "Content-Type: application/json\r\n";
   ResetLastError();
   const int status = WebRequest("POST", endpoint, headers, timeout_ms, post, result, result_headers);
   out.web_retcode = status;
   out.http_status = status;

   if(status == -1)
     {
      const int err_code = GetLastError();
      out.err = StringFormat("WebRequest failed err=%d (add URL in Tools->Options->Expert Advisors)", err_code);
      CTS_LogV(verbose, "CTS AiGate: " + out.err);
      return false;
     }

   string resp = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status < 200 || status >= 300)
     {
      out.err = StringFormat("HTTP %d body=%s", status, resp);
      CTS_LogV(verbose, "CTS AiGate: " + out.err);
      return false;
     }

   if(!CTS_AiGate_ParseJsonDouble(resp, "score", out.score))
     {
      out.err = "parse score failed: " + resp;
      return false;
     }
   if(!CTS_AiGate_ParseJsonDouble(resp, "threshold", out.threshold))
      out.threshold = 0.0;
   if(!CTS_AiGate_ParseJsonBool(resp, "would_allow", out.would_allow))
      out.would_allow = (out.score >= out.threshold);

   out.ok = true;
   return true;
  }

//+------------------------------------------------------------------+
// Returns true if trade path should continue (TryOpen allowed).
bool CTS_AiGate_HandleBeforeOpen(const bool use_ai_gate,
                                 const bool allow_in_tester,
                                 const bool shadow_mode,
                                 const string endpoint,
                                 const int timeout_ms,
                                 const double threshold_fallback,
                                 const string sym,
                                 const ENUM_TIMEFRAMES tf,
                                 const CTSPriceBuf &buf,
                                 const bool bias_long,
                                 const bool bias_short,
                                 const bool sig_long,
                                 const bool sig_short,
                                 const string signal_id,
                                 const bool is_long,
                                 const bool verbose,
                                 string &log_line)
  {
   log_line = "";
   if(!CTS_AiGate_IsActive(use_ai_gate, allow_in_tester, verbose))
      return true;

   string json_body = "";
   if(!CTS_AiGate_BuildFeatureJson(sym, tf, buf, bias_long, bias_short, sig_long, sig_short, json_body))
     {
      log_line = "CTS AiGate: JSON build failed";
      Print(log_line);
      if(shadow_mode)
         return true;
      return false;
     }

   CTSAiScoreResult sc;
   if(!CTS_AiGate_QueryScore(endpoint, timeout_ms, json_body, verbose, sc))
     {
      log_line = StringFormat("CTS AiGate: query failed signal_id=%s side=%s err=%s",
                              signal_id, is_long ? "BUY" : "SELL", sc.err);
      Print(log_line);
      if(shadow_mode)
         return true;
      Print("CTS AiGate: filter mode — skip trade on AI error");
      return false;
     }

   const double thr = (sc.threshold > 0.0) ? sc.threshold : threshold_fallback;
   log_line = StringFormat(
                 "CTS AiGate: signal_id=%s side=%s score=%.4f threshold=%.4f would_allow=%s shadow=%s http=%d",
                 signal_id,
                 is_long ? "BUY" : "SELL",
                 sc.score,
                 thr,
                 sc.would_allow ? "true" : "false",
                 shadow_mode ? "true" : "false",
                 sc.http_status);
   Print(log_line);

   if(shadow_mode)
      return true;

   if(!sc.would_allow)
     {
      PrintFormat("CTS AiGate: filter blocked (score %.4f < threshold %.4f)", sc.score, thr);
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
#endif // CTS_AI_GATE_MQH

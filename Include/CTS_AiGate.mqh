//+------------------------------------------------------------------+
//| CTS_AiGate.mqh — Phase 4/5: AI score + adaptive bucket/threshold from API|
//| Shadow: log only, never block. Filter: allow iff score >= thr_eff (API).  |
//| Filter fail-safe: HTTP/parse errors => skip trade (no silent open).  |
//+------------------------------------------------------------------+
#ifndef CTS_AI_GATE_MQH
#define CTS_AI_GATE_MQH

#include "CTS_Indicators.mqh"
#include "CTS_Log.mqh"

#define CTS_AIGATE_REASON_OK           "ok"
#define CTS_AIGATE_REASON_SHADOW       "shadow"
#define CTS_AIGATE_REASON_FILTER_BLOCK "filter_block"
#define CTS_AIGATE_REASON_FILTER_ERROR "filter_error"
#define CTS_AIGATE_REASON_MOCK_TESTER  "mock_tester"

// Last policy risk_multiplier for the signal about to open (consumed in CTS_TryOpen).
static double g_cts_ai_pending_risk_mult = 1.0;

//+------------------------------------------------------------------+
void CTS_AiGate_PublishRiskMultiplier(const double risk_multiplier)
  {
   g_cts_ai_pending_risk_mult = (risk_multiplier > 0.0) ? risk_multiplier : 1.0;
  }

//+------------------------------------------------------------------+
double CTS_AiGate_ConsumeRiskMultiplier()
  {
   const double m = g_cts_ai_pending_risk_mult;
   g_cts_ai_pending_risk_mult = 1.0;
   return m;
  }

//+------------------------------------------------------------------+
struct CTSAiScoreResult
  {
   bool              ok;
   double            score;
   double            threshold;       // effective (server per-bucket when HTTP)
   bool              would_allow;
   int               http_status;
   int               web_retcode;
   string            err;
   string            source;          // "http" | "mock"
   string            bucket_id;       // Phase 5 adaptive (empty if absent)
   double            risk_multiplier; // logged only; sizing not wired in Week 4
  };

//+------------------------------------------------------------------+
bool CTS_AiGate_UseMockInTester(const bool use_ai_gate,
                                const double mock_score_in_tester)
  {
   if(!use_ai_gate)
      return false;
   if(MQLInfoInteger(MQL_TESTER) == 0)
      return false;
   return (mock_score_in_tester >= 0.0 && mock_score_in_tester <= 1.0);
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_IsActive(const bool use_ai_gate,
                         const bool allow_in_tester,
                         const bool use_mock_in_tester,
                         const bool verbose)
  {
   if(!use_ai_gate)
      return false;
   if(use_mock_in_tester)
      return true;
   if(MQLInfoInteger(MQL_TESTER) != 0 && !allow_in_tester)
     {
      CTS_LogV(verbose, "CTS AiGate: inactive in tester (enable mock score or InpUseAiGateInTester)");
      return false;
     }
   if(!TerminalInfoInteger(TERMINAL_DLLS_ALLOWED))
     {
      CTS_LogV(verbose, "CTS AiGate: TERMINAL_DLLS_ALLOWED is false");
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
bool CTS_AiGate_ValidateMockScore(const double mock_score, string &err)
  {
   err = "";
   if(mock_score < 0.0)
      return true;
   if(mock_score > 1.0)
     {
      err = "AiGate mock score must be in [0,1] or <0 to disable";
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
bool CTS_AiGate_ParseJsonString(const string body, const string key, string &out_val)
  {
   out_val = "";
   const string needle = "\"" + key + "\":";
   int pos = StringFind(body, needle);
   if(pos < 0)
      return false;
   pos += StringLen(needle);
   if(StringSubstr(body, pos, 4) == "null")
      return true;
   if(StringSubstr(body, pos, 1) != "\"")
      return false;
   pos++;
   int end = StringFind(body, "\"", pos);
   if(end < 0)
      return false;
   out_val = StringSubstr(body, pos, end - pos);
   return true;
  }

//+------------------------------------------------------------------+
void CTS_AiGate_FillMock(const double mock_score,
                         const double threshold_ea,
                         const double mock_threshold_eff,
                         const string mock_bucket,
                         const double mock_risk_multiplier,
                         CTSAiScoreResult &out)
  {
   const double thr_eff = (mock_threshold_eff > 0.0 && mock_threshold_eff <= 1.0)
                          ? mock_threshold_eff
                          : threshold_ea;
   out.ok = true;
   out.score = mock_score;
   out.threshold = thr_eff;
   out.would_allow = (mock_score >= thr_eff);
   out.http_status = 0;
   out.web_retcode = 0;
   out.err = "";
   out.source = "mock";
   out.bucket_id = mock_bucket;
   out.risk_multiplier = (mock_risk_multiplier > 0.0) ? mock_risk_multiplier : 1.0;
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
   out.source = "http";
   out.bucket_id = "";
   out.risk_multiplier = 1.0;

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
      out.err = StringFormat("WebRequest err=%d (allow URL http://127.0.0.1:8008 in Expert Advisors)", err_code);
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
   CTS_AiGate_ParseJsonString(resp, "bucket_id", out.bucket_id);
   double rm = 0.0;
   if(CTS_AiGate_ParseJsonDouble(resp, "risk_multiplier", rm) && rm > 0.0)
      out.risk_multiplier = rm;

   out.ok = true;
   return true;
  }

//+------------------------------------------------------------------+
double CTS_AiGate_EffectiveThreshold(const CTSAiScoreResult &sc, const double threshold_ea)
  {
   if(sc.threshold > 0.0 && sc.threshold <= 1.0)
      return sc.threshold;
   return threshold_ea;
  }

//+------------------------------------------------------------------+
bool CTS_AiGate_AllowTrade(const double score, const double threshold_eff)
  {
   return (score >= threshold_eff);
  }

//+------------------------------------------------------------------+
// Returns true if TryOpen should proceed.
bool CTS_AiGate_HandleBeforeOpen(const bool use_ai_gate,
                                 const bool allow_in_tester,
                                 const double mock_score_in_tester,
                                 const double mock_threshold_in_tester,
                                 const string mock_bucket_in_tester,
                                 const double mock_risk_multiplier_in_tester,
                                 const bool shadow_mode,
                                 const string endpoint,
                                 const int timeout_ms,
                                 const double threshold_ea,
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
                                 string &log_line,
                                 string &reason_out)
  {
   log_line = "";
   reason_out = CTS_AIGATE_REASON_OK;

   const bool use_mock = CTS_AiGate_UseMockInTester(use_ai_gate, mock_score_in_tester);
   if(!CTS_AiGate_IsActive(use_ai_gate, allow_in_tester, use_mock, verbose))
     {
      CTS_AiGate_PublishRiskMultiplier(1.0);
      return true;
     }

   CTSAiScoreResult sc;
   if(use_mock)
     {
      string mb = mock_bucket_in_tester;
      StringTrimLeft(mb);
      StringTrimRight(mb);
      CTS_AiGate_FillMock(mock_score_in_tester, threshold_ea, mock_threshold_in_tester, mb,
                          mock_risk_multiplier_in_tester, sc);
      reason_out = CTS_AIGATE_REASON_MOCK_TESTER;
     }
   else
     {
      string json_body = "";
      if(!CTS_AiGate_BuildFeatureJson(sym, tf, buf, bias_long, bias_short, sig_long, sig_short, json_body))
        {
         log_line = "CTS AiGate: JSON build failed";
         Print(log_line);
         reason_out = CTS_AIGATE_REASON_FILTER_ERROR;
         if(shadow_mode)
           {
            CTS_AiGate_PublishRiskMultiplier(1.0);
            return true;
           }
         Print("CTS AiGate: filter fail-safe — skip trade (json build)");
         CTS_AiGate_PublishRiskMultiplier(1.0);
         return false;
        }

      if(!CTS_AiGate_QueryScore(endpoint, timeout_ms, json_body, verbose, sc))
        {
         log_line = StringFormat("CTS AiGate: query failed signal_id=%s side=%s err=%s",
                                 signal_id, is_long ? "BUY" : "SELL", sc.err);
         Print(log_line);
         reason_out = CTS_AIGATE_REASON_FILTER_ERROR;
         if(shadow_mode)
           {
            CTS_AiGate_PublishRiskMultiplier(1.0);
            return true;
           }
         Print("CTS AiGate: filter fail-safe — skip trade (http/timeout)");
         CTS_AiGate_PublishRiskMultiplier(1.0);
         return false;
        }
     }

   const double thr_eff = CTS_AiGate_EffectiveThreshold(sc, threshold_ea);
   const bool allow = CTS_AiGate_AllowTrade(sc.score, thr_eff);
   const string bucket_disp = (StringLen(sc.bucket_id) > 0) ? sc.bucket_id : "-";

   log_line = StringFormat(
                 "CTS AiGate: signal_id=%s side=%s score=%.4f bucket=%s thr_eff=%.4f thr_ea=%.4f risk_mult=%.2f allow=%s shadow=%s src=%s http=%d reason=%s",
                 signal_id,
                 is_long ? "BUY" : "SELL",
                 sc.score,
                 bucket_disp,
                 thr_eff,
                 threshold_ea,
                 sc.risk_multiplier,
                 allow ? "true" : "false",
                 shadow_mode ? "true" : "false",
                 sc.source,
                 sc.http_status,
                 reason_out);
   Print(log_line);

   if(shadow_mode)
     {
      reason_out = CTS_AIGATE_REASON_SHADOW;
      CTS_AiGate_PublishRiskMultiplier(sc.risk_multiplier);
      return true;
     }

   if(!allow)
     {
      reason_out = CTS_AIGATE_REASON_FILTER_BLOCK;
      PrintFormat("CTS AiGate: FILTER BLOCK score=%.4f < thr_eff=%.4f bucket=%s", sc.score, thr_eff, bucket_disp);
      CTS_AiGate_PublishRiskMultiplier(1.0);
      return false;
     }

   reason_out = CTS_AIGATE_REASON_OK;
   CTS_AiGate_PublishRiskMultiplier(sc.risk_multiplier);
   return true;
  }

//+------------------------------------------------------------------+
#endif // CTS_AI_GATE_MQH

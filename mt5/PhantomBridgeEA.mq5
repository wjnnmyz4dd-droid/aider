//+------------------------------------------------------------------+
//|                                            PhantomBridgeEA.mq5   |
//|                                                                  |
//| Hybrid MT5 MQL5 EA Bridge (ADR-023).                             |
//|                                                                  |
//| BRIDGE ONLY. This EA contains no signal-generation, scoring,     |
//| risk, or compliance logic of any kind. Its only trade-initiating |
//| action is executing a command polled from the Phantom backend's |
//| /ea/commands/poll endpoint -- a command that has already passed  |
//| through Phantom's full deterministic pipeline (Data Pipeline ->  |
//| Scanner -> Strategy Engine -> Scoring -> Risk -> Compliance ->   |
//| Execution Validator -> MT5 Bridge) before this EA ever sees it.  |
//|                                                                  |
//| Fail-closed: if the backend cannot be reached within             |
//| FailClosedTimeoutSeconds, or EmergencyDisable is set, this EA    |
//| stops polling for and executing new commands. It never falls    |
//| back to local decision-making.                                  |
//|                                                                  |
//| Phase 1 scope, explicitly: the JSON (de)serialization below is a |
//| minimal, purpose-built implementation for this EA's own fixed    |
//| message schema -- not a general JSON parser/library. See         |
//| MT5_EA_BRIDGE_GUIDE.md for the documented limitation and the     |
//| recommended path (a vendored JSON library) before any live use.  |
//+------------------------------------------------------------------+
#property copyright "Phantom"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- Inputs (ADR-023 "EA requirements") -----------------------------------
input string BackendUrl               = "http://127.0.0.1:8787"; // Phantom backend base URL
input string ApiKey                   = "";                       // X-Phantom-Api-Key
input int    HeartbeatIntervalSeconds = 5;                        // Heartbeat interval
input int    BarSyncIntervalSeconds   = 60;                       // Bar sync interval
input string AllowedSymbolsCsv        = "";                        // Comma-separated allowlist (empty = current chart symbol only)
input long   MagicNumber              = 20260708;                  // Must match EABridgeConfig.magic_number
input int    MaxSlippagePoints        = 20;                        // Deviation passed to CTrade
input int    FailClosedTimeoutSeconds = 30;                        // No successful contact within this window => halt
input bool   EmergencyDisable         = false;                     // Manual kill switch -- never polls/executes when true
input string BarTimeframesCsv         = "M15,H1,H4,D1";            // Timeframes synced to /ea/bars

//--- Globals ---------------------------------------------------------------
CTrade      trade;
datetime    g_last_success_at = 0;
datetime    g_last_bar_sync_at = 0;
bool        g_halted = false;
string      g_allowed_symbols[];
ENUM_TIMEFRAMES g_bar_timeframes[];
string      g_bar_timeframe_names[];

//+------------------------------------------------------------------+
//| Minimal JSON helpers (Phase 1 -- see file header)                 |
//+------------------------------------------------------------------+
string JsonEscape(string value)
  {
   string out = value;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   return out;
  }

string JsonField(string key, string value)
  {
   return "\"" + key + "\":\"" + JsonEscape(value) + "\"";
  }

string JsonFieldNum(string key, double value)
  {
   return "\"" + key + "\":" + DoubleToString(value, 8);
  }

string JsonFieldInt(string key, long value)
  {
   return "\"" + key + "\":" + IntegerToString(value);
  }

string JsonFieldBool(string key, bool value)
  {
   return "\"" + key + "\":" + (value ? "true" : "false");
  }

//--- Extremely small "find one string/number field" reader, sufficient
//--- only for this EA's own fixed, known response shapes -- not a
//--- general JSON parser (documented limitation, ADR-023 file header).
string JsonExtractString(string json, string key)
  {
   string needle = "\"" + key + "\":\"";
   int pos = StringFind(json, needle);
   if(pos < 0) return "";
   int start = pos + StringLen(needle);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
  }

double JsonExtractNumber(string json, string key)
  {
   string needle = "\"" + key + "\":";
   int pos = StringFind(json, needle);
   if(pos < 0) return 0.0;
   int start = pos + StringLen(needle);
   int end = start;
   while(end < StringLen(json))
     {
      ushort c = StringGetCharacter(json, end);
      if((c >= '0' && c <= '9') || c == '.' || c == '-' || c == '+')
         end++;
      else
         break;
     }
   return StringToDouble(StringSubstr(json, start, end - start));
  }

bool JsonExtractBool(string json, string key)
  {
   string needle = "\"" + key + "\":true";
   return StringFind(json, needle) >= 0;
  }

//+------------------------------------------------------------------+
//| HTTP transport (WebRequest -- requires BackendUrl's host to be    |
//| allowlisted in Tools > Options > Expert Advisors)                 |
//+------------------------------------------------------------------+
bool HttpPost(string path, string json_body, string &response)
  {
   string headers = "Content-Type: application/json\r\nX-Phantom-Api-Key: " + ApiKey + "\r\n";
   char post_data[];
   StringToCharArray(json_body, post_data, 0, StringLen(json_body));
   char result[];
   string result_headers;
   int timeout = 5000;
   int status = WebRequest("POST", BackendUrl + path, headers, timeout, post_data, result, result_headers);
   if(status < 0)
     {
      ReportLocalError((int)GetLastError(), "WebRequest POST failed", path);
      return false;
     }
   response = CharArrayToString(result);
   return (status >= 200 && status < 300);
  }

bool HttpGet(string path, string &response)
  {
   string headers = "X-Phantom-Api-Key: " + ApiKey + "\r\n";
   char post_data[];
   char result[];
   string result_headers;
   int timeout = 5000;
   int status = WebRequest("GET", BackendUrl + path, headers, timeout, post_data, result, result_headers);
   if(status < 0)
     {
      ReportLocalError((int)GetLastError(), "WebRequest GET failed", path);
      return false;
     }
   response = CharArrayToString(result);
   return (status >= 200 && status < 300);
  }

//+------------------------------------------------------------------+
//| Outbound telemetry (ADR-023 SS2.1 "may")                          |
//+------------------------------------------------------------------+
void SendHeartbeat()
  {
   string body = "{" +
      JsonFieldInt("magic_number", MagicNumber) + "," +
      JsonField("terminal_time", TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)) + "," +
      JsonFieldBool("connected", TerminalInfoInteger(TERMINAL_CONNECTED)) +
      "}";
   string response;
   if(HttpPost("/ea/heartbeat", body, response))
     {
      g_last_success_at = TimeCurrent();
      if(JsonExtractBool(response, "emergency_stop"))
         g_halted = true;
     }
  }

void SendAccountState()
  {
   string body = "{" +
      JsonFieldInt("magic_number", MagicNumber) + "," +
      JsonFieldNum("equity", AccountInfoDouble(ACCOUNT_EQUITY)) + "," +
      JsonFieldNum("balance", AccountInfoDouble(ACCOUNT_BALANCE)) + "," +
      JsonFieldNum("margin", AccountInfoDouble(ACCOUNT_MARGIN)) + "," +
      JsonFieldNum("free_margin", AccountInfoDouble(ACCOUNT_MARGIN_FREE)) + "," +
      JsonField("currency", AccountInfoString(ACCOUNT_CURRENCY)) +
      "}";
   string response;
   if(HttpPost("/ea/account", body, response))
      g_last_success_at = TimeCurrent();
  }

bool IsSymbolAllowed(string symbol)
  {
   if(ArraySize(g_allowed_symbols) == 0)
      return (symbol == _Symbol);
   for(int i = 0; i < ArraySize(g_allowed_symbols); i++)
      if(g_allowed_symbols[i] == symbol)
         return true;
   return false;
  }

void SendTick(string symbol)
  {
   if(!IsSymbolAllowed(symbol))
      return;
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return;
   string body = "{" +
      JsonField("symbol", symbol) + "," +
      JsonFieldNum("bid", tick.bid) + "," +
      JsonFieldNum("ask", tick.ask) + "," +
      JsonFieldNum("last", tick.last) + "," +
      JsonFieldNum("volume", (double)tick.volume) + "," +
      JsonField("terminal_time", TimeToString(tick.time, TIME_DATE | TIME_SECONDS)) +
      "}";
   string response;
   if(HttpPost("/ea/tick", body, response))
      g_last_success_at = TimeCurrent();
  }

void SendBars()
  {
   if(TimeCurrent() - g_last_bar_sync_at < BarSyncIntervalSeconds)
      return;
   g_last_bar_sync_at = TimeCurrent();

   string bars_json = "";
   int count = 0;
   for(int s = 0; s < MathMax(ArraySize(g_allowed_symbols), 1); s++)
     {
      string symbol = (ArraySize(g_allowed_symbols) > 0) ? g_allowed_symbols[s] : _Symbol;
      for(int t = 0; t < ArraySize(g_bar_timeframes); t++)
        {
         MqlRates rates[];
         if(CopyRates(symbol, g_bar_timeframes[t], 0, 1, rates) != 1)
            continue;
         if(count > 0) bars_json += ",";
         bars_json += "{" +
            JsonField("symbol", symbol) + "," +
            JsonField("timeframe", g_bar_timeframe_names[t]) + "," +
            JsonFieldNum("open", rates[0].open) + "," +
            JsonFieldNum("high", rates[0].high) + "," +
            JsonFieldNum("low", rates[0].low) + "," +
            JsonFieldNum("close", rates[0].close) + "," +
            JsonFieldNum("volume", (double)rates[0].tick_volume) + "," +
            JsonField("bar_time", TimeToString(rates[0].time, TIME_DATE | TIME_SECONDS)) +
            "}";
         count++;
        }
     }
   if(count == 0)
      return;
   string body = "{" + JsonFieldInt("magic_number", MagicNumber) + ",\"bars\":[" + bars_json + "]}";
   string response;
   if(HttpPost("/ea/bars", body, response))
      g_last_success_at = TimeCurrent();
  }

void SendPositions()
  {
   string positions_json = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;
      string direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "UP" : "DOWN";
      if(i > 0) positions_json += ",";
      positions_json += "{" +
         JsonField("position_id", IntegerToString((long)ticket)) + "," +
         JsonField("symbol", PositionGetString(POSITION_SYMBOL)) + "," +
         JsonField("direction", direction) + "," +
         JsonFieldNum("volume", PositionGetDouble(POSITION_VOLUME)) + "," +
         JsonFieldNum("open_price", PositionGetDouble(POSITION_PRICE_OPEN)) + "," +
         JsonFieldNum("stop_loss", PositionGetDouble(POSITION_SL)) + "," +
         JsonFieldNum("take_profit", PositionGetDouble(POSITION_TP)) + "," +
         JsonFieldNum("unrealized_pnl", PositionGetDouble(POSITION_PROFIT)) +
         "}";
     }
   string body = "{" + JsonFieldInt("magic_number", MagicNumber) + ",\"positions\":[" + positions_json + "]}";
   string response;
   if(HttpPost("/ea/positions", body, response))
      g_last_success_at = TimeCurrent();
  }

void ReportLocalError(int code, string message, string context)
  {
   string body = "{" +
      JsonFieldInt("magic_number", MagicNumber) + "," +
      JsonFieldInt("code", code) + "," +
      JsonField("message", message) + "," +
      JsonField("context", context) +
      "}";
   string response;
   // Best-effort -- never blocks/halts the EA on failure to report an error.
   HttpPost("/ea/error/report", body, response);
  }

//+------------------------------------------------------------------+
//| Command relay: poll only already-Phantom-approved commands        |
//| (ADR-023 Hard Rule 1, 4) and execute them via CTrade -- no local  |
//| decision of any kind occurs anywhere below.                       |
//+------------------------------------------------------------------+
void ExecuteOpenCommand(string execution_id, string symbol, string direction, double lot_size,
                        double stop_loss, double take_profit)
  {
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxSlippagePoints);
   bool ok;
   if(direction == "UP")
      ok = trade.Buy(lot_size, symbol, 0.0, stop_loss, take_profit, execution_id);
   else
      ok = trade.Sell(lot_size, symbol, 0.0, stop_loss, take_profit, execution_id);
   ReportExecutionResult(execution_id, ok, ok ? IntegerToString((long)trade.ResultOrder()) : "",
                         ok ? trade.ResultPrice() : 0.0, ok ? trade.ResultVolume() : 0.0,
                         ok ? "" : trade.ResultRetcodeDescription());
  }

void ExecuteAdjustCommand(string execution_id, string position_id, double stop_loss, double take_profit)
  {
   ulong ticket = (ulong)StringToInteger(position_id);
   trade.SetExpertMagicNumber(MagicNumber);
   bool ok = trade.PositionModify(ticket, stop_loss, take_profit);
   ReportExecutionResult(execution_id, ok, position_id, 0.0, 0.0, ok ? "" : trade.ResultRetcodeDescription());
  }

void ExecuteCloseCommand(string execution_id, string position_id, double close_fraction)
  {
   ulong ticket = (ulong)StringToInteger(position_id);
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(MaxSlippagePoints);
   bool ok;
   if(!PositionSelectByTicket(ticket))
     {
      ReportExecutionResult(execution_id, false, position_id, 0.0, 0.0, "position_not_found");
      return;
     }
   double volume = PositionGetDouble(POSITION_VOLUME) * (close_fraction > 0.0 ? close_fraction : 1.0);
   ok = trade.PositionClosePartial(ticket, volume);
   ReportExecutionResult(execution_id, ok, position_id, trade.ResultPrice(), trade.ResultVolume(),
                         ok ? "" : trade.ResultRetcodeDescription());
  }

void ReportExecutionResult(string execution_id, bool success, string broker_ticket,
                           double filled_price, double filled_size, string reason)
  {
   string body = "{" +
      JsonField("execution_id", execution_id) + "," +
      JsonFieldInt("magic_number", MagicNumber) + "," +
      JsonFieldBool("success", success) + "," +
      JsonField("broker_ticket", broker_ticket) + "," +
      JsonFieldNum("filled_price", filled_price) + "," +
      JsonFieldNum("filled_size", filled_size) + "," +
      JsonField("reason", reason) +
      "}";
   string response;
   HttpPost("/ea/execution/report", body, response);
  }

//--- Extracts one command object at index `index` from the poll
//--- response's "commands" array by locating the Nth "{...}" block --
//--- sufficient for this EA's own fixed schema (Phase 1 scope, see
//--- file header), not a general JSON array parser.
bool ExtractCommandAt(string json, int index, string &command_json)
  {
   int pos = StringFind(json, "\"commands\":[");
   if(pos < 0) return false;
   pos += StringLen("\"commands\":[");
   int depth = 0;
   int obj_start = -1;
   int obj_index = -1;
   for(int i = pos; i < StringLen(json); i++)
     {
      ushort c = StringGetCharacter(json, i);
      if(c == '{')
        {
         if(depth == 0) obj_start = i;
         depth++;
        }
      else if(c == '}')
        {
         depth--;
         if(depth == 0)
           {
            obj_index++;
            if(obj_index == index)
              {
               command_json = StringSubstr(json, obj_start, i - obj_start + 1);
               return true;
              }
           }
        }
      else if(c == ']' && depth == 0)
         break;
     }
   return false;
  }

void PollAndExecuteCommands()
  {
   string response;
   if(!HttpGet("/ea/commands/poll?magic_number=" + IntegerToString(MagicNumber), response))
      return;
   g_last_success_at = TimeCurrent();
   if(JsonExtractBool(response, "emergency_stop"))
     {
      g_halted = true;
      return;
     }

   for(int i = 0; i < 50; i++) // bounded -- never an unbounded loop
     {
      string command_json;
      if(!ExtractCommandAt(response, i, command_json))
         break;

      string execution_id = JsonExtractString(command_json, "execution_id");
      string request_kind = JsonExtractString(command_json, "request_kind");
      string symbol = JsonExtractString(command_json, "symbol");
      string direction = JsonExtractString(command_json, "direction");
      string position_id = JsonExtractString(command_json, "position_id");
      long magic_number = (long)JsonExtractNumber(command_json, "magic_number");
      double lot_size = JsonExtractNumber(command_json, "lot_size");
      double stop_loss = JsonExtractNumber(command_json, "stop_loss");
      double take_profit = JsonExtractNumber(command_json, "take_profit");
      double close_fraction = JsonExtractNumber(command_json, "close_fraction");

      // Defensive, redundant re-checks -- the backend already validated
      // these (ADR-023 SS3); the EA never trusts a mismatched magic
      // number or disallowed symbol regardless.
      if(magic_number != MagicNumber)
        {
         ReportExecutionResult(execution_id, false, "", 0.0, 0.0, "magic_number_mismatch");
         continue;
        }
      if(symbol != "" && !IsSymbolAllowed(symbol))
        {
         ReportExecutionResult(execution_id, false, "", 0.0, 0.0, "symbol_not_allowed");
         continue;
        }

      if(request_kind == "OPEN")
         ExecuteOpenCommand(execution_id, symbol, direction, lot_size, stop_loss, take_profit);
      else if(request_kind == "ADJUST")
         ExecuteAdjustCommand(execution_id, position_id, stop_loss, take_profit);
      else if(request_kind == "CLOSE")
         ExecuteCloseCommand(execution_id, position_id, close_fraction);
     }
  }

//+------------------------------------------------------------------+
//| Fail-closed gate (ADR-023 Hard Rule 5)                             |
//+------------------------------------------------------------------+
bool IsFailClosed()
  {
   if(EmergencyDisable)
      return true;
   if(g_halted)
      return true;
   if(g_last_success_at == 0)
      return true; // never yet contacted the backend -- fail closed, not open
   return (TimeCurrent() - g_last_success_at) > FailClosedTimeoutSeconds;
  }

//+------------------------------------------------------------------+
//| Expert event handlers                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   StringSplit(AllowedSymbolsCsv, ',', g_allowed_symbols);
   for(int i = ArraySize(g_allowed_symbols) - 1; i >= 0; i--)
      StringTrimLeft(StringTrimRight(g_allowed_symbols[i]));

   string tf_names[];
   int tf_count = StringSplit(BarTimeframesCsv, ',', tf_names);
   ArrayResize(g_bar_timeframes, tf_count);
   ArrayResize(g_bar_timeframe_names, tf_count);
   for(int i = 0; i < tf_count; i++)
     {
      string name = tf_names[i];
      StringTrimLeft(StringTrimRight(name));
      g_bar_timeframe_names[i] = name;
      if(name == "M15") g_bar_timeframes[i] = PERIOD_M15;
      else if(name == "H1") g_bar_timeframes[i] = PERIOD_H1;
      else if(name == "H4") g_bar_timeframes[i] = PERIOD_H4;
      else if(name == "D1") g_bar_timeframes[i] = PERIOD_D1;
      else g_bar_timeframes[i] = PERIOD_H1;
     }

   if(ApiKey == "")
     {
      Print("PhantomBridgeEA: ApiKey is empty -- refusing to start (fail closed).");
      return(INIT_PARAMETERS_INCORRECT);
     }

   EventSetTimer(MathMax(HeartbeatIntervalSeconds, 1));
   Print("PhantomBridgeEA initialized. Bridge only -- no local trading logic. Backend: ", BackendUrl);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   if(EmergencyDisable)
     {
      // Never polls, never executes, regardless of backend reachability.
      return;
     }

   SendHeartbeat();
   SendAccountState();
   SendPositions();
   SendBars();

   if(IsFailClosed())
     {
      Comment("PhantomBridgeEA: FAIL-CLOSED (no successful backend contact within ",
              FailClosedTimeoutSeconds, "s). Not polling for new commands.");
      return;
     }
   Comment("PhantomBridgeEA: connected, magic=", MagicNumber);
   PollAndExecuteCommands();
  }

void OnTick()
  {
   if(EmergencyDisable || IsFailClosed())
      return;
   SendTick(_Symbol);
  }
//+------------------------------------------------------------------+

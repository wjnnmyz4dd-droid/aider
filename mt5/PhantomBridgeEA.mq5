//+------------------------------------------------------------------+
//| PhantomBridgeEA.mq5                                               |
//| Phase 1 -- PhantomBridgeEA Foundation.                             |
//|                                                                    |
//| The single execution authority for Phantom. This EA is a          |
//| transport + execution bridge ONLY: it never generates, scores, or |
//| sizes a trade. It executes exclusively the six commands           |
//| (BUY, SELL, MODIFY_SL, MODIFY_TP, CLOSE, PARTIAL_CLOSE) it         |
//| receives, already validated, from the Python-side bridge server,  |
//| reports back what actually happened, and fails closed the moment  |
//| it cannot prove the Python side is still reachable.                |
//|                                                                    |
//| Original implementation. No source code from any reference        |
//| repository was copied -- see docs/research/ for the architectural |
//| study this design is informed by.                                  |
//+------------------------------------------------------------------+
#property copyright "Phantom"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- Inputs -----------------------------------------------------------
input string BackendUrl               = "http://127.0.0.1:8787"; // Phantom bridge server base URL
input string ApiKey                   = "";                       // X-Phantom-Api-Key
input int    HeartbeatIntervalSeconds = 5;                        // Heartbeat / telemetry cadence
input string AllowedSymbolsCsv        = "";                        // Comma-separated allowlist (empty = current chart symbol only)
input long   MagicNumber              = 20260709;                  // Must match BridgeConfig.magic_number
input int    MaxSlippagePoints        = 20;                        // Deviation passed to CTrade
input int    FailClosedTimeoutSeconds = 30;                        // No successful contact within this window => halt
input bool   EmergencyDisable         = false;                     // Manual kill switch -- never polls/executes when true
input int    MaxRetries               = 3;                         // Bounded HTTP retry count
input int    RetryDelayMs             = 250;                       // Delay between bounded retries

//--- Globals ------------------------------------------------------------
CTrade   g_trade;
datetime g_lastSuccessfulContact = 0;
datetime g_lastHeartbeatSentAt   = 0;
datetime g_lastTickAt            = 0;
string   g_allowedSymbols[];

const string API_KEY_HEADER = "X-Phantom-Api-Key";

//+------------------------------------------------------------------+
//| Event handling                                                     |
//+------------------------------------------------------------------+
int OnInit()
  {
   ParseAllowedSymbols();
   if(!IsSymbolAllowed(_Symbol))
     {
      Print("PhantomBridgeEA: chart symbol ", _Symbol, " is not in AllowedSymbolsCsv -- refusing to run.");
      return(INIT_FAILED);
     }
   if(ApiKey == "")
     {
      Print("PhantomBridgeEA: ApiKey is empty -- refusing to run.");
      return(INIT_FAILED);
     }
   g_trade.SetExpertMagicNumber(MagicNumber);
   g_trade.SetDeviationInPoints(MaxSlippagePoints);
   // Grace period so the very first fail-closed check doesn't fire
   // before the first heartbeat has had a chance to succeed.
   g_lastSuccessfulContact = TimeCurrent();
   EventSetTimer(1);
   Print("PhantomBridgeEA initialized. Symbol=", _Symbol, " Magic=", MagicNumber);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTick()
  {
   // Evidence the terminal/connection is alive; also used so the
   // fail-closed check never depends solely on the timer having fired.
   g_lastTickAt = TimeCurrent();
  }

void OnTimer()
  {
   if(EmergencyDisable)
      return; // fully halted: no telemetry, no polling, no execution.

   datetime now = TimeCurrent();
   if(now - g_lastHeartbeatSentAt >= HeartbeatIntervalSeconds)
     {
      g_lastHeartbeatSentAt = now;
      SendHeartbeat();
      SendAccountState();
      SendPositions();
      SendPendingOrders();
     }

   if(!IsFailClosed())
      PollAndExecuteCommands();
  }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   // Independent, unsolicited mirror of MT5's own native trade event --
   // a drift-detection cross-check reported alongside, never instead
   // of, this EA's own ExecutionReport for a command it executed.
   SendTradeTransaction(trans, result);
  }

//+------------------------------------------------------------------+
//| Symbol allowlist                                                    |
//+------------------------------------------------------------------+
void ParseAllowedSymbols()
  {
   if(StringLen(AllowedSymbolsCsv) == 0)
     {
      ArrayResize(g_allowedSymbols, 1);
      g_allowedSymbols[0] = _Symbol;
      return;
     }
   int count = StringSplit(AllowedSymbolsCsv, ',', g_allowedSymbols);
   for(int i = 0; i < count; i++)
      StringTrimLeft(StringTrimRight(g_allowedSymbols[i]));
  }

bool IsSymbolAllowed(const string symbol)
  {
   for(int i = 0; i < ArraySize(g_allowedSymbols); i++)
      if(g_allowedSymbols[i] == symbol)
         return(true);
   return(false);
  }

//+------------------------------------------------------------------+
//| Fail-closed                                                         |
//+------------------------------------------------------------------+
bool IsFailClosed()
  {
   if(EmergencyDisable)
      return(true);
   return((TimeCurrent() - g_lastSuccessfulContact) > FailClosedTimeoutSeconds);
  }

//+------------------------------------------------------------------+
//| Minimal JSON helpers -- Phase 1 limitation, deliberately scoped    |
//| to exactly the fixed message shapes this bridge sends/receives.   |
//| Not a general-purpose parser.                                      |
//+------------------------------------------------------------------+
string JsonEscape(const string value)
  {
   string out = value;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   return(out);
  }

// Extract a top-level string field's raw value from a flat JSON object.
// Returns "" if the field is absent or null.
string JsonGetString(const string json, const string key)
  {
   string needle = "\"" + key + "\"";
   int keyPos = StringFind(json, needle);
   if(keyPos < 0)
      return("");
   int colon = StringFind(json, ":", keyPos);
   if(colon < 0)
      return("");
   int i = colon + 1;
   while(i < StringLen(json) && StringGetCharacter(json, i) == ' ')
      i++;
   if(i >= StringLen(json) || StringGetCharacter(json, i) != '"')
      return(""); // not a string (null/number/object) -- callers use the numeric getters instead
   int start = i + 1;
   int end = start;
   while(end < StringLen(json) && StringGetCharacter(json, end) != '"')
     {
      if(StringGetCharacter(json, end) == '\\')
         end++;
      end++;
     }
   return(StringSubstr(json, start, end - start));
  }

double JsonGetDouble(const string json, const string key, const double defaultValue)
  {
   string needle = "\"" + key + "\"";
   int keyPos = StringFind(json, needle);
   if(keyPos < 0)
      return(defaultValue);
   int colon = StringFind(json, ":", keyPos);
   if(colon < 0)
      return(defaultValue);
   int i = colon + 1;
   while(i < StringLen(json) && StringGetCharacter(json, i) == ' ')
      i++;
   int start = i;
   int end = start;
   while(end < StringLen(json) &&
         StringFind("0123456789+-.eE", StringSubstr(json, end, 1)) >= 0)
      end++;
   if(end == start)
      return(defaultValue); // null or non-numeric
   return(StringToDouble(StringSubstr(json, start, end - start)));
  }

long JsonGetLong(const string json, const string key, const long defaultValue)
  {
   return((long)JsonGetDouble(json, key, (double)defaultValue));
  }

// Bounded brace-matching extraction of the Nth object in a top-level
// JSON array field. Returns "" once index is out of range.
string JsonGetArrayObjectAt(const string json, const string arrayKey, const int index)
  {
   string needle = "\"" + arrayKey + "\"";
   int keyPos = StringFind(json, needle);
   if(keyPos < 0)
      return("");
   int bracket = StringFind(json, "[", keyPos);
   if(bracket < 0)
      return("");
   int pos = bracket + 1;
   int found = -1;
   int length = StringLen(json);
   while(pos < length)
     {
      while(pos < length && (StringGetCharacter(json, pos) == ' ' || StringGetCharacter(json, pos) == ','))
         pos++;
      if(pos >= length || StringGetCharacter(json, pos) == ']')
         break;
      if(StringGetCharacter(json, pos) != '{')
         break; // malformed -- Phase 1 limitation, not a general parser
      int depth = 0;
      int objStart = pos;
      while(pos < length)
        {
         ushort ch = StringGetCharacter(json, pos);
         if(ch == '{')
            depth++;
         else if(ch == '}')
           {
            depth--;
            if(depth == 0)
              {
               pos++;
               break;
              }
           }
         pos++;
        }
      found++;
      if(found == index)
         return(StringSubstr(json, objStart, pos - objStart));
     }
   return("");
  }

//+------------------------------------------------------------------+
//| Bounded-retry HTTP helpers                                          |
//+------------------------------------------------------------------+
string HttpPost(const string endpoint, const string jsonBody, int &statusOut)
  {
   statusOut = 0;
   uchar postData[];
   int len = StringToCharArray(jsonBody, postData, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   ArrayResize(postData, len);

   string headers = "Content-Type: application/json\r\n" + API_KEY_HEADER + ": " + ApiKey + "\r\n";
   uchar result[];
   string resultHeaders;

   for(int attempt = 0; attempt < MaxRetries; attempt++)
     {
      ResetLastError();
      int status = WebRequest("POST", BackendUrl + endpoint, headers, 5000, postData, result, resultHeaders);
      if(status >= 200 && status < 300)
        {
         statusOut = status;
         g_lastSuccessfulContact = TimeCurrent();
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      if(status > 0)
        {
         // A real HTTP response, just not success -- do not treat as a
         // dead link, but do not retry a validation rejection either.
         statusOut = status;
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      // status <= 0: WebRequest itself failed (network/DNS/not-allowed) -- retry.
      if(attempt + 1 < MaxRetries)
         Sleep(RetryDelayMs);
     }
   return("");
  }

string HttpGet(const string endpoint, int &statusOut)
  {
   statusOut = 0;
   uchar postData[];
   string headers = API_KEY_HEADER + ": " + ApiKey + "\r\n";
   uchar result[];
   string resultHeaders;

   for(int attempt = 0; attempt < MaxRetries; attempt++)
     {
      ResetLastError();
      int status = WebRequest("GET", BackendUrl + endpoint, headers, 5000, postData, result, resultHeaders);
      if(status >= 200 && status < 300)
        {
         statusOut = status;
         g_lastSuccessfulContact = TimeCurrent();
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      if(status > 0)
        {
         statusOut = status;
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      if(attempt + 1 < MaxRetries)
         Sleep(RetryDelayMs);
     }
   return("");
  }

//+------------------------------------------------------------------+
//| Telemetry senders                                                    |
//+------------------------------------------------------------------+
void SendHeartbeat()
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"account_login\":%d,\"terminal_connected\":%s}",
      JsonEscape(ApiKey), (int)MagicNumber, (int)AccountInfoInteger(ACCOUNT_LOGIN),
      TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false");
   int status;
   HttpPost("/bridge/heartbeat", body, status);
  }

void SendAccountState()
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,\"currency\":\"%s\",\"leverage\":%d}",
      JsonEscape(ApiKey), (int)MagicNumber,
      AccountInfoDouble(ACCOUNT_BALANCE), AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_MARGIN), AccountInfoDouble(ACCOUNT_MARGIN_FREE),
      AccountInfoString(ACCOUNT_CURRENCY), (int)AccountInfoInteger(ACCOUNT_LEVERAGE));
   int status;
   HttpPost("/bridge/account", body, status);
  }

void SendPositions()
  {
   string items = "";
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket))
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;
      string direction = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      if(items != "")
         items += ",";
      items += StringFormat(
         "{\"position_id\":\"%I64u\",\"symbol\":\"%s\",\"direction\":\"%s\",\"volume\":%.2f,\"open_price\":%.5f,\"stop_loss\":%.5f,\"take_profit\":%.5f,\"unrealized_pnl\":%.2f}",
         ticket, PositionGetString(POSITION_SYMBOL), direction,
         PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN),
         PositionGetDouble(POSITION_SL), PositionGetDouble(POSITION_TP),
         PositionGetDouble(POSITION_PROFIT));
     }
   string body = StringFormat("{\"api_key\":\"%s\",\"magic_number\":%d,\"positions\":[%s]}",
                               JsonEscape(ApiKey), (int)MagicNumber, items);
   int status;
   HttpPost("/bridge/positions", body, status);
  }

void SendPendingOrders()
  {
   string items = "";
   int total = OrdersTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != MagicNumber)
         continue;
      if(items != "")
         items += ",";
      items += StringFormat(
         "{\"order_id\":\"%I64u\",\"symbol\":\"%s\",\"order_type\":\"%d\",\"volume\":%.2f,\"price\":%.5f,\"stop_loss\":%.5f,\"take_profit\":%.5f}",
         ticket, OrderGetString(ORDER_SYMBOL), (int)OrderGetInteger(ORDER_TYPE),
         OrderGetDouble(ORDER_VOLUME_CURRENT), OrderGetDouble(ORDER_PRICE_OPEN),
         OrderGetDouble(ORDER_SL), OrderGetDouble(ORDER_TP));
     }
   string body = StringFormat("{\"api_key\":\"%s\",\"magic_number\":%d,\"orders\":[%s]}",
                               JsonEscape(ApiKey), (int)MagicNumber, items);
   int status;
   HttpPost("/bridge/orders", body, status);
  }

void SendTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeResult &result)
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"symbol\":\"%s\",\"deal_ticket\":\"%I64u\",\"order_ticket\":\"%I64u\",\"transaction_type\":\"%d\",\"volume\":%.2f,\"price\":%.5f}",
      JsonEscape(ApiKey), (int)MagicNumber, trans.symbol,
      trans.deal, trans.order, (int)trans.type, result.volume, result.price);
   int status;
   HttpPost("/bridge/trade-transaction", body, status);
  }

void ReportError(const string errorCode, const string message, const string context)
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"error_code\":\"%s\",\"message\":\"%s\",\"context\":\"%s\"}",
      JsonEscape(ApiKey), (int)MagicNumber, errorCode, JsonEscape(message), JsonEscape(context));
   int status;
   HttpPost("/bridge/error", body, status);
  }

void ReportExecutionResult(const string correlationId, const bool success, const ulong ticket,
                            const double price, const double volume, const string errorCode)
  {
   string errorField = (errorCode == "") ? "null" : ("\"" + errorCode + "\"");
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"correlation_id\":\"%s\",\"magic_number\":%d,\"success\":%s,\"broker_ticket\":\"%I64u\",\"filled_price\":%.5f,\"filled_volume\":%.2f,\"error_code\":%s}",
      JsonEscape(ApiKey), correlationId, (int)MagicNumber, success ? "true" : "false",
      ticket, price, volume, errorField);
   int status;
   HttpPost("/bridge/execution/report", body, status);
  }

//+------------------------------------------------------------------+
//| Trade execution -- exactly the six responsibilities in scope.       |
//| Every modify/close operation re-verifies magic-number ownership     |
//| before touching a position, even though the server already          |
//| validated the command -- defense in depth, never trusted alone.     |
//+------------------------------------------------------------------+
void ExecuteBuy(const string correlationId, const string symbol, const double volume,
                const double stopLoss, const double takeProfit)
  {
   if(!IsSymbolAllowed(symbol))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "SYMBOL_NOT_ALLOWED");
      return;
     }
   bool ok = g_trade.Buy(volume, symbol, 0.0, stopLoss, takeProfit, "phantom");
   if(ok)
      ReportExecutionResult(correlationId, true, g_trade.ResultOrder(), g_trade.ResultPrice(), volume, "");
   else
      ReportExecutionResult(correlationId, false, 0, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

void ExecuteSell(const string correlationId, const string symbol, const double volume,
                 const double stopLoss, const double takeProfit)
  {
   if(!IsSymbolAllowed(symbol))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "SYMBOL_NOT_ALLOWED");
      return;
     }
   bool ok = g_trade.Sell(volume, symbol, 0.0, stopLoss, takeProfit, "phantom");
   if(ok)
      ReportExecutionResult(correlationId, true, g_trade.ResultOrder(), g_trade.ResultPrice(), volume, "");
   else
      ReportExecutionResult(correlationId, false, 0, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

bool SelectOwnedPosition(const string positionId)
  {
   ulong ticket = (ulong)StringToInteger(positionId);
   if(ticket == 0 || !PositionSelectByTicket(ticket))
      return(false);
   return(PositionGetInteger(POSITION_MAGIC) == MagicNumber);
  }

void ExecuteModifySL(const string correlationId, const string positionId, const double newSl)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   double currentTp = PositionGetDouble(POSITION_TP);
   bool ok = g_trade.PositionModify(ticket, newSl, currentTp);
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, 0, 0, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

void ExecuteModifyTP(const string correlationId, const string positionId, const double newTp)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   double currentSl = PositionGetDouble(POSITION_SL);
   bool ok = g_trade.PositionModify(ticket, currentSl, newTp);
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, 0, 0, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

void ExecuteClose(const string correlationId, const string positionId)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   double volume = PositionGetDouble(POSITION_VOLUME);
   bool ok = g_trade.PositionClose(ticket, MaxSlippagePoints);
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, g_trade.ResultPrice(), volume, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

void ExecutePartialClose(const string correlationId, const string positionId, const double closeVolume)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   double ownedVolume = PositionGetDouble(POSITION_VOLUME);
   if(closeVolume <= 0 || closeVolume >= ownedVolume)
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, "INVALID_PARTIAL_CLOSE_VOLUME");
      return;
     }
   bool ok = g_trade.PositionClosePartial(ticket, closeVolume, MaxSlippagePoints);
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, g_trade.ResultPrice(), closeVolume, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(g_trade.ResultRetcode()));
  }

//+------------------------------------------------------------------+
//| Command polling and dispatch                                        |
//+------------------------------------------------------------------+
void PollAndExecuteCommands()
  {
   int status;
   string response = HttpGet("/bridge/commands/poll?magic_number=" + IntegerToString((int)MagicNumber), status);
   if(response == "")
      return; // no successful contact this cycle -- handled by the fail-closed check next tick

   // Bounded to avoid any possibility of an unbounded loop on a
   // malformed or hostile response.
   for(int i = 0; i < 50; i++)
     {
      string cmd = JsonGetArrayObjectAt(response, "commands", i);
      if(cmd == "")
         break;

      string correlationId = JsonGetString(cmd, "correlation_id");
      string kind           = JsonGetString(cmd, "command_kind");
      string symbol         = JsonGetString(cmd, "symbol");
      long   magic          = JsonGetLong(cmd, "magic_number", -1);

      if(magic != MagicNumber)
        {
         // Redundant defense-in-depth re-check -- the server already
         // filters by magic number, but this EA never trusts a single
         // layer alone.
         continue;
        }

      if(kind == "BUY")
         ExecuteBuy(correlationId, symbol, JsonGetDouble(cmd, "volume", 0.0),
                    JsonGetDouble(cmd, "stop_loss", 0.0), JsonGetDouble(cmd, "take_profit", 0.0));
      else if(kind == "SELL")
         ExecuteSell(correlationId, symbol, JsonGetDouble(cmd, "volume", 0.0),
                     JsonGetDouble(cmd, "stop_loss", 0.0), JsonGetDouble(cmd, "take_profit", 0.0));
      else if(kind == "MODIFY_SL")
         ExecuteModifySL(correlationId, JsonGetString(cmd, "position_id"), JsonGetDouble(cmd, "stop_loss", 0.0));
      else if(kind == "MODIFY_TP")
         ExecuteModifyTP(correlationId, JsonGetString(cmd, "position_id"), JsonGetDouble(cmd, "take_profit", 0.0));
      else if(kind == "CLOSE")
         ExecuteClose(correlationId, JsonGetString(cmd, "position_id"));
      else if(kind == "PARTIAL_CLOSE")
         ExecutePartialClose(correlationId, JsonGetString(cmd, "position_id"), JsonGetDouble(cmd, "close_volume", 0.0));
      else
         ReportError("UNKNOWN_COMMAND_KIND", "Received an unrecognized command_kind", kind);
     }
  }
//+------------------------------------------------------------------+

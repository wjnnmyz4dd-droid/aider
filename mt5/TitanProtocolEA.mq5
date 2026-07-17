//+------------------------------------------------------------------+
//| TitanProtocolEA.mq5                                               |
//| Phase 1 -- TitanProtocolEA Foundation.                             |
//|                                                                    |
//| The single execution authority for Titan Protocol. This EA is a          |
//| transport + execution bridge ONLY: it never generates, scores, or |
//| sizes a trade. It executes exclusively the six commands           |
//| (BUY, SELL, MODIFY_SL, MODIFY_TP, CLOSE, PARTIAL_CLOSE) it         |
//| receives, already validated, from the Python-side bridge server,  |
//| reports back what actually happened, and fails closed the moment  |
//| it cannot prove the Python side is still reachable.                |
//|                                                                    |
//| Amendment 1 (ADR-023): also reports its own chart's closed bars   |
//| and latest tick to the Bridge's new /bridge/market-data endpoint  |
//| -- transport only, same as everything else here. All validation, |
//| normalization, ordering, and freshness logic lives exclusively in |
//| titan_protocol/market_data_ingestion/, never duplicated in MQL5.  |
//|                                                                    |
//| ADR-034: Transport=Socket switches every one of the message types |
//| above onto a persistent native MQL5 TCP socket (SocketCreate/     |
//| SocketConnect family) instead of WebRequest()/HTTP -- the same    |
//| message bodies, the same routes, the same fail-closed semantics,  |
//| just a different substrate underneath. Transport=Http (default)  |
//| is entirely unchanged and remains the rollback path.              |
//|                                                                    |
//| Original implementation. No source code from any reference        |
//| repository was copied -- see docs/research/ for the architectural |
//| study this design is informed by.                                  |
//+------------------------------------------------------------------+
#property copyright "Titan Protocol"
#property version   "1.01"
#property strict

#include <Trade/Trade.mqh>

//--- Inputs -----------------------------------------------------------
input string BackendUrl               = "http://127.0.0.1:8787"; // Titan Protocol bridge server base URL
input string ApiKey                   = "";                       // X-Titan-Protocol-Api-Key
input int    HeartbeatIntervalSeconds = 5;                        // Heartbeat / telemetry cadence
input string AllowedSymbolsCsv        = "";                        // Comma-separated allowlist (empty = current chart symbol only)
input long   MagicNumber              = 20260710;                  // Must match BridgeConfig.magic_number
input int    MaxSlippagePoints        = 20;                        // Deviation passed to CTrade
input int    FailClosedTimeoutSeconds = 30;                        // No successful contact within this window => halt
input bool   EmergencyDisable         = false;                     // Manual kill switch -- never polls/executes when true
input int    MaxRetries               = 3;                         // Bounded HTTP retry count
input int    RetryDelayMs             = 250;                       // Delay between bounded HTTP retries
input int    MaxRequoteRetries        = 2;                         // Bounded trade-level retry count on requote/price-changed only
input int    RequoteRetryDelayMs      = 100;                       // Delay between bounded requote retries
input bool   DiagnosticMode           = false;                     // Transport-only HTTP diagnostics -- no behavior change when false

//--- ADR-034: transport substrate selection -----------------------------
enum ENUM_TRANSPORT_MODE
  {
   TRANSPORT_HTTP,    // WebRequest()/HTTP -- today's transport, the rollback path
   TRANSPORT_SOCKET   // native MQL5 TCP socket -- ADR-034
  };

input ENUM_TRANSPORT_MODE Transport         = TRANSPORT_SOCKET;    // ADR-034 transport substrate (Amendment 2 default; Http = rollback path)
input string SocketHost                     = "127.0.0.1";         // Bridge socket host (Transport=Socket only)
input int    SocketPort                     = 8788;                // Bridge socket port -- must match BridgeConfig.socket_port
input int    SocketConnectTimeoutMs         = 5000;                // SocketConnect() timeout
input int    SocketReadTimeoutMs            = 5000;                // SocketRead() timeout per response frame
input int    SocketReconnectBaseDelayMs     = 500;                 // First reconnect backoff delay
input int    SocketReconnectMaxDelayMs      = 15000;                // Reconnect backoff ceiling
input int    SocketMaxMessageBytes          = 65536;                // Must match BridgeConfig.socket_max_message_bytes
input int    SocketFailoverAfterAttempts    = 5;                     // ADR-034 Amendment 3: consecutive failed reconnects before auto-falling back to HTTP (0 = never auto-fallback)

//--- Globals ------------------------------------------------------------
CTrade   g_trade;
datetime g_lastSuccessfulContact = 0;
datetime g_lastHeartbeatSentAt   = 0;
datetime g_lastTickAt            = 0;
string   g_allowedSymbols[];

// ADR-034 -- socket transport state. `g_socketSeq` resets to 0 on every
// fresh connection, deliberately: the Bridge's own replay guard (seq
// must strictly increase) is scoped per-TCP-connection, so a new
// connection legitimately starts a new sequence space -- never a
// duplicate of the previous connection's sequence, since the Bridge
// never remembers sequence state across connections either.
int      g_socket               = INVALID_HANDLE;
long     g_socketSeq            = 0;
datetime g_lastConnectAttemptAt = 0;
int      g_reconnectAttempt     = 0;

// ADR-034 Amendment 3 -- the `Transport` input is read-only at runtime
// (MQL5 inputs cannot be reassigned), so an automatic fallback needs its
// own runtime-mutable variable. Starts equal to `Transport`; once
// SocketFailoverAfterAttempts consecutive reconnect attempts fail, this
// (and only this) flips to TRANSPORT_HTTP for the remainder of the run.
// Every BridgeRequest()/BridgePollCommands() call consults this, never
// the raw `Transport` input directly.
ENUM_TRANSPORT_MODE g_effectiveTransport = TRANSPORT_SOCKET;
bool                g_hasFallenBackToHttp = false;

// Amendment 1 (ADR-023) -- market-data reporting state.
datetime g_lastBarOpenTime = 0;
long     g_barSequence     = 0;

// Final Release Hardening -- server-side emergency-stop sync. Learned
// only from /bridge/commands/poll's own `emergency_stop` field, never
// polled via a separate endpoint -- one source of truth, no duplicate
// state machine. Independent of, and OR'd with, the local
// EmergencyDisable input (see IsEmergencyStopped()).
bool g_serverEmergencyStop = false;

const string API_KEY_HEADER = "X-Titan-Protocol-Api-Key";
// ADR-034 -- must match titan_protocol/bridge/socket_transport.py's
// _COMMANDS_POLL_ROUTE exactly; the one route name with no 1:1 HTTP
// POST-path counterpart in _ROUTE_TO_HTTP_PATH (HTTP's form is a GET
// with a query string, not a POST body).
const string _COMMANDS_POLL_ROUTE = "commands_poll";

//+------------------------------------------------------------------+
//| Event handling                                                     |
//+------------------------------------------------------------------+
int OnInit()
  {
   ParseAllowedSymbols();
   if(!IsSymbolAllowed(_Symbol))
     {
      Print("TitanProtocolEA: chart symbol ", _Symbol, " is not in AllowedSymbolsCsv -- refusing to run.");
      return(INIT_FAILED);
     }
   if(ApiKey == "")
     {
      Print("TitanProtocolEA: ApiKey is empty -- refusing to run.");
      return(INIT_FAILED);
     }
   if(Transport == TRANSPORT_SOCKET && SocketHost == "")
     {
      Print("TitanProtocolEA: Transport=Socket requires a non-empty SocketHost -- refusing to run.");
      return(INIT_FAILED);
     }
   g_trade.SetExpertMagicNumber(MagicNumber);
   g_trade.SetDeviationInPoints(MaxSlippagePoints);
   // Grace period so the very first fail-closed check doesn't fire
   // before the first heartbeat has had a chance to succeed.
   g_lastSuccessfulContact = TimeCurrent();
   // ADR-034 Amendment 3 -- starts equal to the Transport input; may
   // fall back to TRANSPORT_HTTP at runtime (see EnsureSocketConnected).
   g_effectiveTransport = Transport;
   g_hasFallenBackToHttp = false;
   EventSetTimer(1);
   // Deployment-bug fix (GetLastError=4014 despite the allow-list having
   // been edited): TERMINAL_DATA_PATH/TERMINAL_PATH are real, documented
   // MQL5 identifiers (TerminalInfoString) -- printing them here gives
   // the operator (and deployment_windows/verify_mt5_instance.py, via
   // this same Experts-log line) an unambiguous answer to "which
   // terminal's Tools>Options>Expert Advisors do I need to check",
   // instead of guessing when more than one MT5 installation exists.
   Print("TitanProtocolEA initialized. Symbol=", _Symbol, " Magic=", MagicNumber, " Transport=", EnumToString(Transport));
   Print("TitanProtocolEA terminal instance -- TERMINAL_PATH=", TerminalInfoString(TERMINAL_PATH),
         " TERMINAL_DATA_PATH=", TerminalInfoString(TERMINAL_DATA_PATH));
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_socket != INVALID_HANDLE)
     {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
     }
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
      SendTick(); // Amendment 1 -- same cadence as the rest of telemetry
     }

   CheckAndSendNewBar(); // Amendment 1 -- driven by real bar formation, not a timer interval

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
     {
      // StringTrimLeft/StringTrimRight modify their string argument by
      // reference and return an int (characters removed) -- they must
      // never be nested, since the inner call's int return value can't
      // be passed as the outer call's string& parameter.
      StringTrimLeft(g_allowedSymbols[i]);
      StringTrimRight(g_allowedSymbols[i]);
     }
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

// Final Release Hardening -- effective emergency-stopped state is the
// local operator kill switch OR the server-reported emergency stop
// (learned via /bridge/commands/poll's `emergency_stop` field). Used to
// reject execution of any already-received command; it does NOT by
// itself halt polling/telemetry the way EmergencyDisable's own OnTimer
// early-return does, since the EA must keep polling to learn when a
// server-side stop clears.
bool IsEmergencyStopped()
  {
   return(EmergencyDisable || g_serverEmergencyStop);
  }

//+------------------------------------------------------------------+
//| Pre-flight trading-capability checks -- run before every trade    |
//| attempt, never after. Each returns "" (no issue) or a named,      |
//| stable reason string; nothing here silently proceeds on a         |
//| precondition failure.                                              |
//+------------------------------------------------------------------+
string CheckTradingPreconditions(const string symbol, const bool isOpeningNewPosition)
  {
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      return("TERMINAL_TRADE_NOT_ALLOWED");
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
      return("ACCOUNT_TRADE_NOT_ALLOWED");
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))
      return("EXPERT_TRADE_NOT_ALLOWED");
   if(!SymbolSelect(symbol, true))
      return("SYMBOL_NOT_AVAILABLE");
   long tradeMode = SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE);
   if(tradeMode == SYMBOL_TRADE_MODE_DISABLED)
      return("SYMBOL_TRADE_DISABLED");
   // Close-only mode blocks new exposure but must never block closing
   // an existing position -- callers pass isOpeningNewPosition=false
   // for MODIFY_SL/MODIFY_TP/CLOSE/PARTIAL_CLOSE.
   if(isOpeningNewPosition && tradeMode == SYMBOL_TRADE_MODE_CLOSEONLY)
      return("SYMBOL_CLOSE_ONLY");
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return("MARKET_CLOSED_OR_NO_QUOTES");
   return("");
  }

string CheckVolumeValid(const string symbol, const double volume)
  {
   double minVol = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxVol = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double stepVol = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(volume < minVol)
      return("VOLUME_BELOW_MIN");
   if(volume > maxVol)
      return("VOLUME_ABOVE_MAX");
   if(stepVol > 0.0)
     {
      double steps = MathRound((volume - minVol) / stepVol);
      double normalized = minVol + steps * stepVol;
      if(MathAbs(normalized - volume) > 0.0000001)
         return("VOLUME_NOT_STEP_ALIGNED");
     }
   return("");
  }

// Validates one stop price (SL or TP, whichever is being set/changed)
// against the symbol's minimum stop distance, relative to the current
// market price on the relevant side. Pass 0.0 for whichever of
// stopLoss/takeProfit is not being checked.
string CheckStopsValid(const string symbol, const bool isBuy, const double stopLoss, const double takeProfit)
  {
   long stopsLevelPoints = SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double minDistance = stopsLevelPoints * point;
   double referencePrice = isBuy ? SymbolInfoDouble(symbol, SYMBOL_ASK) : SymbolInfoDouble(symbol, SYMBOL_BID);
   if(stopLoss > 0.0)
     {
      double slDistance = isBuy ? (referencePrice - stopLoss) : (stopLoss - referencePrice);
      if(slDistance < minDistance)
         return("STOP_LOSS_TOO_CLOSE");
     }
   if(takeProfit > 0.0)
     {
      double tpDistance = isBuy ? (takeProfit - referencePrice) : (referencePrice - takeProfit);
      if(tpDistance < minDistance)
         return("TAKE_PROFIT_TOO_CLOSE");
     }
   return("");
  }

//+------------------------------------------------------------------+
//| Requote handling -- identify the two MT5 retcodes that mean       |
//| "the price moved, not that the request was invalid," and retry    |
//| only those, only up to MaxRequoteRetries, entirely within the      |
//| same command execution. Exactly one ExecutionReport is ever sent   |
//| per correlation_id regardless of how many internal attempts this   |
//| takes -- retrying never duplicates the reported result.            |
//+------------------------------------------------------------------+
bool IsRequoteRetcode(const uint retcode)
  {
   return(retcode == TRADE_RETCODE_REQUOTE || retcode == TRADE_RETCODE_PRICE_CHANGED);
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

// Extract a top-level `true`/`false` literal field. Returns defaultValue
// if the key is absent or the value is neither literal (e.g. null).
bool JsonGetBool(const string json, const string key, const bool defaultValue)
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
   if(StringSubstr(json, i, 4) == "true")
      return(true);
   if(StringSubstr(json, i, 5) == "false")
      return(false);
   return(defaultValue);
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

// Bounded brace-matching extraction of a top-level JSON *object* field
// (as opposed to JsonGetArrayObjectAt's array-of-objects case) -- used
// by the socket transport to pull the response envelope's "body" object
// back out for callers, which always expect the *body*, never the
// outer {"seq":...,"status":...,"body":{...}} envelope. Returns "" if
// the key is absent or its value is not an object.
string JsonGetObject(const string json, const string key)
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
   if(i >= StringLen(json) || StringGetCharacter(json, i) != '{')
      return("");
   int depth = 0;
   int objStart = i;
   int pos = i;
   int length = StringLen(json);
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
   return(StringSubstr(json, objStart, pos - objStart));
  }

//+------------------------------------------------------------------+
//| Diagnostics-only helper (DiagnosticMode) -- never called, and     |
//| costs nothing, unless the input is explicitly turned on. Prints   |
//| exactly the transport-level facts needed to tell apart a          |
//| WebRequest()-layer failure from a real-but-rejected HTTP response, |
//| never the API key or any account/credential value.                |
//+------------------------------------------------------------------+
void LogHttpDiagnostics(const string method, const string url, const int payloadBytes,
                         const string headers, const bool apiKeyPresent,
                         const int webRequestReturn, const int lastError, const uint elapsedMs,
                         const string responseHeaders, const string responseBody)
  {
   int headerCount = 0;
   int pos = 0;
   while(true)
     {
      pos = StringFind(headers, "\r\n", pos);
      if(pos < 0)
         break;
      headerCount++;
      pos += 2;
     }
   Print("======== TITAN HTTP ========");
   Print("Method: ", method);
   Print("URL: ", url);
   Print("Return: ", webRequestReturn);
   Print("GetLastError(): ", lastError);
   Print("Elapsed: ", elapsedMs, " ms");
   Print("Payload bytes: ", payloadBytes);
   Print("Header bytes: ", StringLen(headers));
   Print("Header count: ", headerCount);
   Print("API Key: ", apiKeyPresent ? "Present" : "Absent");
   Print("Response Headers: ", (StringLen(responseHeaders) > 0 ? responseHeaders : "<empty>"));
   Print("Response Body: ", (StringLen(responseBody) > 0 ? responseBody : "<empty>"));
   Print("============================");
  }

// Deployment-bug fix -- 4014 persists in the field even after an
// operator adds the URL to Tools>Options>Expert Advisors, most often
// because the allow-list change does not take effect for an
// already-attached EA (and in many MT5 builds, not even for a
// re-attached one) -- a FULL terminal restart is frequently required.
// Printed once per HttpPost/HttpGet call (first attempt only, not on
// every retry) so the Experts log states the fix and the exact
// terminal instance in one place, rather than just the bare error code.
void PrintWebRequestWhitelistGuidance(const string method, const string endpoint, int lastErr)
  {
   // Runtime Audit Phase 3 -- unconditional, greppable marker: WebRequest()
   // itself never reached the Bridge (status<=0, GetLastError set) --
   // this is the evidence a request was blocked before it left MT5/Windows,
   // as distinct from the Bridge receiving and then rejecting it.
   Print("TITAN_DIAG BLOCKED transport=HTTP method=", method, " endpoint=", endpoint,
         " lastError=", lastErr, " time=", TimeToIsoString(TimeCurrent()));
   Print("TitanProtocolEA: ", method, " ", endpoint, " WebRequest failed, GetLastError=", lastErr,
         " (4014 = URL not in Tools>Options>Expert Advisors whitelist)");
   if(lastErr == 4014)
     {
      Print("TitanProtocolEA: if you have ALREADY added ", BackendUrl, " to that list and this "
            "still fails, a re-attach is often not enough -- fully close and reopen MT5, then "
            "reattach the EA. Confirm you are editing the allow-list in THIS terminal instance: "
            "TERMINAL_DATA_PATH=", TerminalInfoString(TERMINAL_DATA_PATH));
     }
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
   string fullUrl = BackendUrl + endpoint;

   for(int attempt = 0; attempt < MaxRetries; attempt++)
     {
      ResetLastError();
      uint startTick = DiagnosticMode ? GetTickCount() : 0;
      int status = WebRequest("POST", fullUrl, headers, 5000, postData, result, resultHeaders);
      int lastErr = GetLastError();
      if(DiagnosticMode)
         LogHttpDiagnostics("POST", fullUrl, ArraySize(postData), headers, StringLen(ApiKey) > 0,
                             status, lastErr, GetTickCount() - startTick, resultHeaders,
                             CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
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
         Print("TitanProtocolEA: POST ", endpoint, " rejected, HTTP ", status, ": ",
               CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      // status <= 0: WebRequest itself failed (network/DNS/not-allowed) -- retry.
      PrintWebRequestWhitelistGuidance("POST", endpoint, lastErr);
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
   string fullUrl = BackendUrl + endpoint;

   for(int attempt = 0; attempt < MaxRetries; attempt++)
     {
      ResetLastError();
      uint startTick = DiagnosticMode ? GetTickCount() : 0;
      int status = WebRequest("GET", fullUrl, headers, 5000, postData, result, resultHeaders);
      int lastErr = GetLastError();
      if(DiagnosticMode)
         LogHttpDiagnostics("GET", fullUrl, ArraySize(postData), headers, StringLen(ApiKey) > 0,
                             status, lastErr, GetTickCount() - startTick, resultHeaders,
                             CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
      if(status >= 200 && status < 300)
        {
         statusOut = status;
         g_lastSuccessfulContact = TimeCurrent();
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      if(status > 0)
        {
         statusOut = status;
         Print("TitanProtocolEA: GET ", endpoint, " rejected, HTTP ", status, ": ",
               CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
         return(CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8));
        }
      PrintWebRequestWhitelistGuidance("GET", endpoint, lastErr);
      if(attempt + 1 < MaxRetries)
         Sleep(RetryDelayMs);
     }
   return("");
  }

//+------------------------------------------------------------------+
//| ADR-034 -- native MQL5 socket transport. Same message bodies, same |
//| routes, same fail-closed semantics as the HTTP transport above --  |
//| only the substrate underneath changes. Every function here mirrors|
//| an HTTP counterpart 1:1: EnsureSocketConnected ~ nothing (HTTP is  |
//| stateless per-call), SocketRequest ~ HttpPost/HttpGet.             |
//+------------------------------------------------------------------+
void LogSocketDiagnostics(const string operation, const bool success, const long detail)
  {
   if(!DiagnosticMode)
      return;
   Print("======== TITAN SOCKET ========");
   Print("Operation: ", operation);
   Print("Success: ", success ? "true" : "false");
   Print("Detail: ", detail);
   Print("Connected: ", (g_socket != INVALID_HANDLE && SocketIsConnected(g_socket)) ? "true" : "false");
   Print("===============================");
  }

// ADR-034 Amendment 3 -- called after every failed connection attempt.
// Once SocketFailoverAfterAttempts consecutive attempts have failed,
// permanently (for the rest of this run) switches g_effectiveTransport
// to HTTP so BridgeRequest()/BridgePollCommands() stop calling into the
// socket path at all. SocketFailoverAfterAttempts=0 disables this
// (never auto-fallback -- keep retrying Socket forever).
void CheckSocketFailoverThreshold()
  {
   if(SocketFailoverAfterAttempts <= 0)
      return;
   if(g_hasFallenBackToHttp || g_effectiveTransport != TRANSPORT_SOCKET)
      return;
   if(g_reconnectAttempt < SocketFailoverAfterAttempts)
      return;
   g_effectiveTransport = TRANSPORT_HTTP;
   g_hasFallenBackToHttp = true;
   Print("TitanProtocolEA: Socket transport failed ", g_reconnectAttempt,
         " consecutive connection attempts -- automatically falling back to HTTP transport "
         "for the remainder of this run (ADR-034 Amendment 3). To restore Socket transport, "
         "verify Tools>Options>Expert Advisors permits this EA's socket address, then "
         "remove and reattach the EA.");
  }

// Lazily (re)connects the persistent socket, honoring an exponential
// reconnect backoff (base * 2^attempt, capped) so a down Bridge is
// retried with increasing patience rather than hammered every OnTimer
// tick. Returns true only if the socket is connected and usable right
// now -- callers must never send on a socket this returned false for.
bool EnsureSocketConnected()
  {
   if(g_socket != INVALID_HANDLE && SocketIsConnected(g_socket))
      return(true);

   if(g_socket != INVALID_HANDLE)
     {
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
     }

   datetime now = TimeCurrent();
   int cappedAttempt = (g_reconnectAttempt > 10) ? 10 : g_reconnectAttempt;
   int delayMs = (int)MathMin((double)SocketReconnectBaseDelayMs * MathPow(2.0, cappedAttempt),
                               (double)SocketReconnectMaxDelayMs);
   if(g_lastConnectAttemptAt != 0 && ((long)(now - g_lastConnectAttemptAt)) * 1000 < delayMs)
      return(false); // still backing off -- not yet time to retry

   g_lastConnectAttemptAt = now;
   g_socket = SocketCreate();
   if(g_socket == INVALID_HANDLE)
     {
      Print("TITAN_DIAG BLOCKED transport=Socket operation=SocketCreate lastError=", GetLastError(),
            " time=", TimeToIsoString(TimeCurrent()));
      Print("TitanProtocolEA: SocketCreate failed, GetLastError=", GetLastError());
      LogSocketDiagnostics("SocketCreate", false, GetLastError());
      g_reconnectAttempt++;
      CheckSocketFailoverThreshold();
      return(false);
     }
   if(!SocketConnect(g_socket, SocketHost, (uint)SocketPort, SocketConnectTimeoutMs))
     {
      Print("TITAN_DIAG BLOCKED transport=Socket operation=SocketConnect host=", SocketHost,
            " port=", SocketPort, " lastError=", GetLastError(),
            " time=", TimeToIsoString(TimeCurrent()));
      Print("TitanProtocolEA: SocketConnect to ", SocketHost, ":", SocketPort, " failed, GetLastError=", GetLastError(),
            " (4014 = address not in Tools>Options>Expert Advisors whitelist)");
      LogSocketDiagnostics("SocketConnect", false, GetLastError());
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      g_reconnectAttempt++;
      CheckSocketFailoverThreshold();
      return(false);
     }
   Print("TitanProtocolEA: socket connected to ", SocketHost, ":", SocketPort);
   LogSocketDiagnostics("SocketConnect", true, 0);
   g_socketSeq = 0;      // fresh connection -- fresh sequence space
   g_reconnectAttempt = 0;
   return(true);
  }

// Sends one length-prefixed frame: a 4-byte big-endian payload length
// followed by that many bytes of UTF-8 JSON -- the same framing
// `titan_protocol/bridge/socket_transport.py`'s `encode_frame`/
// `read_frame` implement, byte for byte.
bool SocketSendFrame(const string jsonBody)
  {
   uchar payload[];
   int payloadLen = StringToCharArray(jsonBody, payload, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   ArrayResize(payload, payloadLen);

   uchar frame[];
   ArrayResize(frame, 4 + payloadLen);
   frame[0] = (uchar)((payloadLen >> 24) & 0xFF);
   frame[1] = (uchar)((payloadLen >> 16) & 0xFF);
   frame[2] = (uchar)((payloadLen >> 8) & 0xFF);
   frame[3] = (uchar)(payloadLen & 0xFF);
   ArrayCopy(frame, payload, 4, 0, payloadLen);

   int sent = SocketSend(g_socket, frame, ArraySize(frame));
   return(sent == ArraySize(frame));
  }

// Blocking read of exactly `count` bytes, looping across as many
// SocketRead() calls as needed -- this is what makes a partial-packet
// response transparent to callers, mirroring the Bridge's own
// `_recv_exact`. Returns false on timeout, error, or a closed
// connection; never returns a short buffer.
bool SocketReadExact(uchar &buffer[], const int count)
  {
   ArrayResize(buffer, count);
   int have = 0;
   while(have < count)
     {
      uchar chunk[];
      int want = count - have;
      ArrayResize(chunk, want);
      int got = SocketRead(g_socket, chunk, want, SocketReadTimeoutMs);
      if(got <= 0)
         return(false); // timeout, error, or connection closed
      ArrayCopy(buffer, chunk, have, 0, got);
      have += got;
     }
   return(true);
  }

// Reads and returns one complete frame's JSON payload, or "" on any
// failure (timeout/closed/oversized) -- callers treat "" exactly like
// HttpPost/HttpGet's own "no successful contact" return. An oversized
// declared length closes the connection outright (framing trust is
// broken once a claimed length is refused), mirroring the Bridge's own
// `FrameTooLargeError` handling.
string SocketReadFrame()
  {
   uchar header[];
   if(!SocketReadExact(header, 4))
      return("");
   long length = ((long)header[0] << 24) | ((long)header[1] << 16) | ((long)header[2] << 8) | (long)header[3];
   if(length < 0 || length > SocketMaxMessageBytes)
     {
      Print("TitanProtocolEA: socket frame declares ", length, " bytes, exceeding SocketMaxMessageBytes -- closing connection.");
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      return("");
     }
   uchar body[];
   if(!SocketReadExact(body, (int)length))
      return("");
   return(CharArrayToString(body, 0, WHOLE_ARRAY, CP_UTF8));
  }

// Sends one {"seq":N,"route":route,"body":bodyJson} envelope and
// returns the response envelope's "body" object, exactly matching
// HttpPost/HttpGet's own return contract ("" = no successful contact
// this cycle). `bodyJson` is the identical JSON object every existing
// Send*/Report* function already builds for the HTTP transport -- no
// second body-construction path exists anywhere in this file.
string SocketRequest(const string route, const string bodyJson, int &statusOut)
  {
   statusOut = 0;
   if(!EnsureSocketConnected())
      return("");

   g_socketSeq++;
   string envelope = StringFormat("{\"seq\":%d,\"route\":\"%s\",\"body\":%s}",
                                   (int)g_socketSeq, route, bodyJson);
   if(!SocketSendFrame(envelope))
     {
      Print("TITAN_DIAG BLOCKED transport=Socket operation=SocketSend route=", route,
            " lastError=", GetLastError(), " time=", TimeToIsoString(TimeCurrent()));
      Print("TitanProtocolEA: socket send failed for route ", route, ", GetLastError=", GetLastError());
      LogSocketDiagnostics("SocketSend:" + route, false, GetLastError());
      SocketClose(g_socket);
      g_socket = INVALID_HANDLE;
      return("");
     }

   string response = SocketReadFrame();
   if(response == "")
     {
      // Runtime Audit Phase 3 -- distinct from BLOCKED: the frame was
      // sent successfully (the bytes left this process), but no reply
      // arrived before the read timeout/connection closed. This does NOT
      // prove the request never reached the Bridge -- it may have been
      // received and even processed, with only the response lost -- so
      // it is deliberately not classified as either "blocked before the
      // Bridge" or "Bridge responded"; a diagnostic reading this log
      // must treat it as its own, honestly-labeled case.
      Print("TITAN_DIAG NO_RESPONSE transport=Socket route=", route,
            " time=", TimeToIsoString(TimeCurrent()));
      LogSocketDiagnostics("SocketRead:" + route, false, 0);
      return("");
     }

   statusOut = (int)JsonGetLong(response, "status", 0);
   LogSocketDiagnostics("SocketRequest:" + route, statusOut >= 200 && statusOut < 300, statusOut);
   if(statusOut >= 200 && statusOut < 300)
      g_lastSuccessfulContact = TimeCurrent();
   return(JsonGetObject(response, "body"));
  }

// Transport-agnostic wrapper -- every Send*/Report* function below
// calls this instead of HttpPost directly, so Transport=Http and
// Transport=Socket share one body-construction call site each. Reads
// g_effectiveTransport (ADR-034 Amendment 3), never the raw Transport
// input directly -- this is what makes the automatic HTTP fallback
// actually take effect once triggered.
string BridgeRequest(const string route, const string httpEndpoint, const string bodyJson, int &statusOut)
  {
   // Runtime Audit Phase 3 -- unconditional (not gated by DiagnosticMode),
   // one line per logical request, printed before any transport-layer
   // call is made. This is the sole evidence that "MT5 attempted this
   // request at all" can ever rest on -- everything after this point
   // (WebRequest/SocketSend succeeding, failing, or the Bridge's own
   // response) is a separate, later fact; this line's mere presence or
   // absence in the Experts log is what tells the two apart.
   Print("TITAN_DIAG ATTEMPT route=", route, " transport=",
         (g_effectiveTransport == TRANSPORT_SOCKET ? "Socket" : "HTTP"),
         " time=", TimeToIsoString(TimeCurrent()));
   if(g_effectiveTransport == TRANSPORT_SOCKET)
      return(SocketRequest(route, bodyJson, statusOut));
   return(HttpPost(httpEndpoint, bodyJson, statusOut));
  }

// Transport-agnostic command-poll wrapper -- HTTP's GET-with-query-
// string becomes a socket request whose body carries the same
// api_key/magic_number fields the HTTP query string carries today.
string BridgePollCommands(int &statusOut)
  {
   // Runtime Audit Phase 3 -- see BridgeRequest()'s own comment; same
   // unconditional attempt marker, same reasoning.
   Print("TITAN_DIAG ATTEMPT route=", _COMMANDS_POLL_ROUTE, " transport=",
         (g_effectiveTransport == TRANSPORT_SOCKET ? "Socket" : "HTTP"),
         " time=", TimeToIsoString(TimeCurrent()));
   if(g_effectiveTransport == TRANSPORT_SOCKET)
     {
      string body = StringFormat("{\"api_key\":\"%s\",\"magic_number\":%d}", JsonEscape(ApiKey), (int)MagicNumber);
      return(SocketRequest(_COMMANDS_POLL_ROUTE, body, statusOut));
     }
   return(HttpGet("/bridge/commands/poll?magic_number=" + IntegerToString((int)MagicNumber), statusOut));
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
   BridgeRequest("heartbeat", "/bridge/heartbeat", body, status);
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
   BridgeRequest("account", "/bridge/account", body, status);
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
   BridgeRequest("positions", "/bridge/positions", body, status);
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
   BridgeRequest("orders", "/bridge/orders", body, status);
  }

//+------------------------------------------------------------------+
//| Market data reporting (Amendment 1, ADR-023) -- transport only.   |
//| No validation, normalization, ordering, or freshness logic lives  |
//| here; that is exclusively titan_protocol/market_data_ingestion/'s |
//| job on the Python side. This EA reports one chart's own bars/tick |
//| -- the timeframe it actually has (the chart's own period).        |
//+------------------------------------------------------------------+
string PeriodToTimeframeString(const ENUM_TIMEFRAMES period)
  {
   switch(period)
     {
      case PERIOD_M1:  return("M1");
      case PERIOD_M5:  return("M5");
      case PERIOD_M15: return("M15");
      case PERIOD_M30: return("M30");
      case PERIOD_H1:  return("H1");
      case PERIOD_H4:  return("H4");
      case PERIOD_D1:  return("D1");
      default:         return(""); // unsupported chart timeframe -- market data not published
     }
  }

// MT5's TimeToString() produces "YYYY.MM.DD HH:MM:SS" -- reformatted
// into an ISO-8601 string Python's datetime.fromisoformat() parses
// directly. Broker/server time is treated as the reference clock this
// whole deployment already assumes (Bridge and MT5 run on the same
// machine in this release's supported topology) -- see the Amendment 1
// implementation report for the known limitation this simplifies.
string TimeToIsoString(const datetime value)
  {
   string formatted = TimeToString(value, TIME_DATE | TIME_SECONDS);
   StringReplace(formatted, ".", "-");
   StringReplace(formatted, " ", "T");
   return(formatted + "+00:00");
  }

// This Phase 1 EA has exactly one clock source available to it
// (MT5's own TimeCurrent()) -- source_timestamp deliberately mirrors
// broker_timestamp rather than using TimeLocal(), which reflects the
// operator's PC timezone and would produce false-positive CLOCK_SKEW
// rejections against MarketDataIngestionConfig's tight 5-second
// default tolerance for any operator not in the broker's own timezone.
// Reporting two genuinely identical readings is honest; reporting a
// timezone difference as "skew" would not be.
void SendClosedBar(const string timeframe, const MqlRates &bar)
  {
   g_barSequence++;
   string isoNow      = TimeToIsoString(TimeCurrent());
   string isoBarOpen   = TimeToIsoString(bar.time);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   string bidField = (bid > 0.0) ? StringFormat("%.5f", bid) : "null";
   string askField = (ask > 0.0) ? StringFormat("%.5f", ask) : "null";
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"bar\":{\"symbol\":\"%s\",\"timeframe\":\"%s\","
      "\"broker_timestamp\":\"%s\",\"source_timestamp\":\"%s\",\"bar_open_time\":\"%s\","
      "\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,\"volume\":%.2f,"
      "\"is_closed\":true,\"sequence_number\":%d,\"bid\":%s,\"ask\":%s}}",
      JsonEscape(ApiKey), (int)MagicNumber, _Symbol, timeframe,
      isoNow, isoNow, isoBarOpen,
      bar.open, bar.high, bar.low, bar.close, (double)bar.tick_volume,
      (int)g_barSequence, bidField, askField);
   int status;
   BridgeRequest("market_data", "/bridge/market-data", body, status);
  }

// Detects a newly-closed bar by watching the chart's own forming-bar
// (index 0) open time advance -- the standard MQL5 "new bar" signal.
// The first time this EA ever notices a bar boundary it only records
// the timestamp (there is no "bar before the first one seen" to
// report); every boundary after that reports the bar that just closed
// (now at index 1) via CopyRates, never a fabricated one.
void CheckAndSendNewBar()
  {
   string tf = PeriodToTimeframeString(_Period);
   if(tf == "")
      return;

   datetime currentOpenTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(currentOpenTime == 0 || currentOpenTime == g_lastBarOpenTime)
      return;

   if(g_lastBarOpenTime != 0)
     {
      MqlRates rates[];
      if(CopyRates(_Symbol, PERIOD_CURRENT, 1, 1, rates) == 1)
         SendClosedBar(tf, rates[0]);
     }
   g_lastBarOpenTime = currentOpenTime;
  }

void SendTick()
  {
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return; // market closed / no quotes -- nothing honest to report
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"tick\":{\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f}}",
      JsonEscape(ApiKey), (int)MagicNumber, _Symbol, bid, ask);
   int status;
   BridgeRequest("market_data", "/bridge/market-data", body, status);
  }

void SendTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeResult &result)
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"symbol\":\"%s\",\"deal_ticket\":\"%I64u\",\"order_ticket\":\"%I64u\",\"transaction_type\":\"%d\",\"volume\":%.2f,\"price\":%.5f}",
      JsonEscape(ApiKey), (int)MagicNumber, trans.symbol,
      trans.deal, trans.order, (int)trans.type, result.volume, result.price);
   int status;
   BridgeRequest("trade_transaction", "/bridge/trade-transaction", body, status);
  }

void ReportError(const string errorCode, const string message, const string context)
  {
   string body = StringFormat(
      "{\"api_key\":\"%s\",\"magic_number\":%d,\"error_code\":\"%s\",\"message\":\"%s\",\"context\":\"%s\"}",
      JsonEscape(ApiKey), (int)MagicNumber, errorCode, JsonEscape(message), JsonEscape(context));
   int status;
   BridgeRequest("error", "/bridge/error", body, status);
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
   BridgeRequest("execution_report", "/bridge/execution/report", body, status);
  }

//+------------------------------------------------------------------+
//| Trade execution -- exactly the six responsibilities in scope.       |
//| Every modify/close operation re-verifies magic-number ownership     |
//| before touching a position, even though the server already          |
//| validated the command -- defense in depth, never trusted alone.     |
//| Every operation: (1) runs pre-flight capability checks, (2) runs    |
//| volume/stops validation where applicable, (3) attempts execution    |
//| with a bounded retry restricted to requote/price-changed retcodes   |
//| only, (4) reports exactly once, using CTrade's actual result        |
//| (never the originally-requested volume) as the filled amount.       |
//+------------------------------------------------------------------+
void ExecuteBuy(const string correlationId, const string symbol, const double volume,
                const double stopLoss, const double takeProfit)
  {
   if(!IsSymbolAllowed(symbol))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "SYMBOL_NOT_ALLOWED");
      return;
     }
   string precondition = CheckTradingPreconditions(symbol, true);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, precondition);
      return;
     }
   string volumeIssue = CheckVolumeValid(symbol, volume);
   if(volumeIssue != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, volumeIssue);
      return;
     }
   string stopsIssue = CheckStopsValid(symbol, true, stopLoss, takeProfit);
   if(stopsIssue != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, stopsIssue);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      ok = g_trade.Buy(volume, symbol, 0.0, stopLoss, takeProfit, "titan_protocol");
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, g_trade.ResultOrder(), g_trade.ResultPrice(), g_trade.ResultVolume(), "");
   else
      ReportExecutionResult(correlationId, false, 0, 0, 0, IntegerToString(retcode));
  }

void ExecuteSell(const string correlationId, const string symbol, const double volume,
                 const double stopLoss, const double takeProfit)
  {
   if(!IsSymbolAllowed(symbol))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "SYMBOL_NOT_ALLOWED");
      return;
     }
   string precondition = CheckTradingPreconditions(symbol, true);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, precondition);
      return;
     }
   string volumeIssue = CheckVolumeValid(symbol, volume);
   if(volumeIssue != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, volumeIssue);
      return;
     }
   string stopsIssue = CheckStopsValid(symbol, false, stopLoss, takeProfit);
   if(stopsIssue != "")
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, stopsIssue);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      ok = g_trade.Sell(volume, symbol, 0.0, stopLoss, takeProfit, "titan_protocol");
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, g_trade.ResultOrder(), g_trade.ResultPrice(), g_trade.ResultVolume(), "");
   else
      ReportExecutionResult(correlationId, false, 0, 0, 0, IntegerToString(retcode));
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
   string symbol = PositionGetString(POSITION_SYMBOL);
   bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double currentTp = PositionGetDouble(POSITION_TP);

   string precondition = CheckTradingPreconditions(symbol, false);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, precondition);
      return;
     }
   string stopsIssue = CheckStopsValid(symbol, isBuy, newSl, 0.0);
   if(stopsIssue != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, stopsIssue);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      if(!PositionSelectByTicket(ticket))
        {
         ReportExecutionResult(correlationId, false, ticket, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
         return;
        }
      ok = g_trade.PositionModify(ticket, newSl, currentTp);
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, 0, 0, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(retcode));
  }

void ExecuteModifyTP(const string correlationId, const string positionId, const double newTp)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   string symbol = PositionGetString(POSITION_SYMBOL);
   bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
   double currentSl = PositionGetDouble(POSITION_SL);

   string precondition = CheckTradingPreconditions(symbol, false);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, precondition);
      return;
     }
   string stopsIssue = CheckStopsValid(symbol, isBuy, 0.0, newTp);
   if(stopsIssue != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, stopsIssue);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      if(!PositionSelectByTicket(ticket))
        {
         ReportExecutionResult(correlationId, false, ticket, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
         return;
        }
      ok = g_trade.PositionModify(ticket, currentSl, newTp);
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, 0, 0, "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(retcode));
  }

void ExecuteClose(const string correlationId, const string positionId)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   string symbol = PositionGetString(POSITION_SYMBOL);

   string precondition = CheckTradingPreconditions(symbol, false);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, precondition);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      if(!PositionSelectByTicket(ticket))
        {
         ReportExecutionResult(correlationId, false, ticket, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
         return;
        }
      ok = g_trade.PositionClose(ticket, (ulong)MaxSlippagePoints);
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, g_trade.ResultPrice(), g_trade.ResultVolume(), "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(retcode));
  }

void ExecutePartialClose(const string correlationId, const string positionId, const double closeVolume)
  {
   if(!SelectOwnedPosition(positionId))
     {
      ReportExecutionResult(correlationId, false, 0, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
      return;
     }
   ulong ticket = (ulong)StringToInteger(positionId);
   string symbol = PositionGetString(POSITION_SYMBOL);
   double ownedVolume = PositionGetDouble(POSITION_VOLUME);
   if(closeVolume <= 0 || closeVolume >= ownedVolume)
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, "INVALID_PARTIAL_CLOSE_VOLUME");
      return;
     }

   string precondition = CheckTradingPreconditions(symbol, false);
   if(precondition != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, precondition);
      return;
     }
   string volumeIssue = CheckVolumeValid(symbol, closeVolume);
   if(volumeIssue != "")
     {
      ReportExecutionResult(correlationId, false, ticket, 0, 0, volumeIssue);
      return;
     }

   bool ok = false;
   uint retcode = 0;
   for(int attempt = 0; attempt <= MaxRequoteRetries; attempt++)
     {
      if(!PositionSelectByTicket(ticket))
        {
         ReportExecutionResult(correlationId, false, ticket, 0, 0, "UNKNOWN_OR_FOREIGN_POSITION");
         return;
        }
      ok = g_trade.PositionClosePartial(ticket, closeVolume, (ulong)MaxSlippagePoints);
      retcode = g_trade.ResultRetcode();
      if(ok || !IsRequoteRetcode(retcode))
         break;
      if(attempt < MaxRequoteRetries)
         Sleep(RequoteRetryDelayMs);
     }
   if(ok)
      ReportExecutionResult(correlationId, true, ticket, g_trade.ResultPrice(), g_trade.ResultVolume(), "");
   else
      ReportExecutionResult(correlationId, false, ticket, 0, 0, IntegerToString(retcode));
  }

//+------------------------------------------------------------------+
//| Command polling and dispatch                                        |
//+------------------------------------------------------------------+
void PollAndExecuteCommands()
  {
   int status;
   string response = BridgePollCommands(status);
   if(response == "")
      return; // no successful contact this cycle -- handled by the fail-closed check next tick

   // Final Release Hardening -- learn the server's emergency-stop state
   // from this same poll response (no separate endpoint, no duplicate
   // state machine). Logged only on transition, never every cycle.
   bool newServerEmergencyStop = JsonGetBool(response, "emergency_stop", false);
   if(newServerEmergencyStop != g_serverEmergencyStop)
     {
      if(newServerEmergencyStop)
         Print("TitanProtocolEA: server-side emergency stop ACTIVATED -- rejecting new execution commands locally until cleared.");
      else
         Print("TitanProtocolEA: server-side emergency stop CLEARED -- resuming normal command execution.");
      g_serverEmergencyStop = newServerEmergencyStop;
     }

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

      if(IsEmergencyStopped())
        {
         // Defense-in-depth: the server should already stop queuing new
         // commands during an emergency stop, but this EA never relies
         // on a single layer alone -- reject execution locally too.
         // Existing positions are never auto-closed here.
         ReportError("EMERGENCY_STOP_ACTIVE", "Command rejected -- local or server-side emergency stop is active", correlationId);
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

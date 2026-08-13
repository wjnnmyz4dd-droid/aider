//+------------------------------------------------------------------+
//|                                    SessionEdgeExecutionEA.mq5     |
//|                    Session Edge - MT5 Execution Adapter (Phase 3) |
//|                                                                  |
//| EXECUTION ADAPTER ONLY. This Expert Advisor is a *consumer* of    |
//| the Session Edge Filesystem Execution Bridge. It reads validated  |
//| trade instructions the strategy engine produced, submits the      |
//| corresponding MT5 market orders, and writes back acknowledgements |
//| and deterministic execution results.                              |
//|                                                                  |
//| IT NEVER contains strategy logic. It does not compute market      |
//| structure, breakouts, retests, price action, health gates, news,  |
//| risk, stops or targets, and it never decides or changes trade     |
//| direction. Direction / entry / stop / target come verbatim from   |
//| the validated instruction. No indicators, no price-series reads,  |
//| no back-testing, no optimization, no prediction.                  |
//|                                                                  |
//| BOUNDARIES: no HTTP, no sockets, no REST/RPC, no external APIs,    |
//| no news feeds, no external process execution. Only the MT5 trade  |
//| API and the filesystem bridge.                                    |
//|                                                                  |
//| This source mirrors the executable reference/specification in     |
//| execution_consumer.py one-to-one. It targets a real MetaTrader 5  |
//| terminal and is compiled with MetaEditor; it is NOT compiled or   |
//| run in the project CI (no terminal / compiler on that platform).  |
//+------------------------------------------------------------------+
#property copyright "Session Edge"
#property version   "1.00"
#property strict
#property description "Session Edge MT5 Execution Adapter - bridge consumer, execution only."

#include <Trade\Trade.mqh>
#include "JsonBridge.mqh"

//--- inputs (operational config; NOT strategy parameters) -----------
input string BridgeRoot      = "session_edge_bridge"; // bridge_root, under MQL5\Files (or common)
input bool   UseCommonFolder = false;                 // true => terminal common Files folder
input double DefaultVolume   = 0.10;                  // DEPRECATED (M9): NOT used for production
                                                      // execution; volume is authoritative in the
                                                      // instruction. Retained only as an inert input.
input string BrokerSuffix    = "";                    // appended to the 6-char base symbol
input string EaId            = "SessionEdgeExecutionEA/1.0";
input int    PollSeconds     = 5;                      // bridge poll cadence (no busy-wait)
input long   MagicNumber     = 920240125;

//--- allow-lists mirror bridge/config.py ----------------------------
// PR-3J/M9: the production instruction schema is 3 (adds a required, authoritative
// ``volume`` — the executable lot sized upstream and proven within risk-per-trade by
// compliance; the EA executes it VERBATIM and never sizes from risk_fraction or the
// DefaultVolume input). This MUST equal bridge/config.py schema_version_allowlist; a
// source-parity test guards divergence. Schema 1 (London-only) and schema 2 (no
// authoritative volume) are retired and fail closed here.
#define ALLOW_SCHEMA_VERSION   3
#define ALLOW_STRATEGY_ID      "forex_swing_orb"
#define ALLOW_STRATEGY_VERSION "swing_orb.v1.4.0"
#define FUTURE_SKEW_SEC        60

//--- terminal states (mirror bridge/contract.py ResultState) --------
#define ST_EXECUTED         "EXECUTED"
#define ST_EXECUTION_FAILED "EXECUTION_FAILED"
#define ST_REJECTED         "REJECTED"
#define ST_EXPIRED          "EXPIRED"
#define ST_DUPLICATE        "DUPLICATE"

CTrade   g_trade;
bool     g_recovered = false;

//+------------------------------------------------------------------+
string Path(const string sub, const string name) { return BridgeRoot + "\\" + sub + name; }

//+------------------------------------------------------------------+
//| sha256(payload)[:16] - deterministic ids (result_id / ack_id).   |
//+------------------------------------------------------------------+
string Sha256Hex16(const string payload)
{
   uchar bytes[];
   int n = StringToCharArray(payload, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0 && bytes[n-1] == 0) n--;
   string hex = Sha256Hex(bytes, n);
   return (StringLen(hex) >= 16) ? StringSubstr(hex, 0, 16) : "";
}

string ResultId(const string sid, const string status) { return Sha256Hex16(sid + "|" + status); }
string AckId(const string sid)                          { return Sha256Hex16(sid + "|ACK"); }

string ResultName(const string sid, const string status) { return sid + "." + ResultId(sid, status) + ".json"; }
string AckName(const string sid)                         { return sid + "." + AckId(sid) + ".ack.json"; }

//+------------------------------------------------------------------+
//| Deterministic UTC ISO-8601 'Z' stamp for the current server GMT.  |
//+------------------------------------------------------------------+
string NowIso()
{
   MqlDateTime t; TimeToStruct(TimeGMT(), t);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",
                       t.year, t.mon, t.day, t.hour, t.min, t.sec);
}

//+------------------------------------------------------------------+
//| Canonical symbol (EURUSD.FX) -> broker symbol. Pure string map -  |
//| NOT strategy logic. Returns "" if not a canonical .FX symbol.     |
//+------------------------------------------------------------------+
string NormalizeSymbol(const string canonical)
{
   int len = StringLen(canonical);
   if(len != 9 || StringSubstr(canonical, 6, 3) != ".FX")
      return "";
   string base = StringSubstr(canonical, 0, 6);
   for(int i = 0; i < 6; i++)
   {
      ushort c = StringGetCharacter(base, i);
      if(c < 'A' || c > 'Z') return "";
   }
   return base + BrokerSuffix;
}

//+------------------------------------------------------------------+
//| Dedup (mirror SeenResolver): terminal iff a result or archive     |
//| artifact exists for this signal_id.                               |
//+------------------------------------------------------------------+
bool SeenTerminal(const string sid, string &family)
{
   if(BridgeExists(Path(BR_ACC, sid + ".json"), UseCommonFolder)) { family = "ACCEPTED"; return true; }
   if(BridgeExists(Path(BR_REJ, sid + ".json"), UseCommonFolder)) { family = "REJECTED"; return true; }
   if(BridgeExists(Path(BR_RESULTS, ResultName(sid, ST_EXECUTED)), UseCommonFolder))         { family = "ACCEPTED"; return true; }
   if(BridgeExists(Path(BR_RESULTS, ResultName(sid, ST_EXECUTION_FAILED)), UseCommonFolder)) { family = "REJECTED"; return true; }
   if(BridgeExists(Path(BR_RESULTS, ResultName(sid, ST_REJECTED)), UseCommonFolder))         { family = "REJECTED"; return true; }
   if(BridgeExists(Path(BR_RESULTS, ResultName(sid, ST_EXPIRED)), UseCommonFolder))          { family = "REJECTED"; return true; }
   if(BridgeExists(Path(BR_RESULTS, ResultName(sid, ST_DUPLICATE)), UseCommonFolder))        { family = "REJECTED"; return true; }
   return false;
}

//+------------------------------------------------------------------+
//| Ticket<->signal_id correlation from the terminal (broker truth).  |
//+------------------------------------------------------------------+
ulong BrokerTicketByComment(const string sid)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_COMMENT) == sid)
         return ticket;
   }
   return 0;
}

//+------------------------------------------------------------------+
//| Append a JSON line to the deterministic audit log.               |
//+------------------------------------------------------------------+
void Audit(const string action, const string outcome, const string reason,
           const string sid, const string detail)
{
   string line = StringFormat(
      "{\"action\":\"%s\",\"detail\":%s,\"outcome\":\"%s\",\"reason_code\":\"%s\",\"signal_id\":\"%s\",\"timestamp\":\"%s\"}",
      action, (StringLen(detail) ? detail : "{}"), outcome, reason,
      (StringLen(sid) ? sid : "null"), NowIso());
   int flags = FILE_READ | FILE_WRITE | FILE_BIN | FILE_SHARE_READ | FILE_SHARE_WRITE;
   if(UseCommonFolder) flags |= FILE_COMMON;
   int h = FileOpen(Path(BR_HEALTH, "audit.jsonl"), flags);
   if(h == INVALID_HANDLE) return;
   FileSeek(h, 0, SEEK_END);
   uchar bytes[]; string s = line + "\n";
   int n = StringToCharArray(s, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0 && bytes[n-1] == 0) n--;
   FileWriteArray(h, bytes, 0, n);
   FileFlush(h);
   FileClose(h);
}

//+------------------------------------------------------------------+
//| Write the acknowledgement (non-terminal) once ownership is taken. |
//+------------------------------------------------------------------+
void WriteAck(const string sid, const string symbol, const string direction)
{
   string detail = StringFormat(
      "{\"ea_id\":\"%s\",\"mt5_account_id\":\"%I64d\",\"mt5_terminal_id\":\"%s\",\"terminal_state\":\"ACK\"}",
      EaId, AccountInfoInteger(ACCOUNT_LOGIN),
      TerminalInfoString(TERMINAL_NAME));
   string json = StringFormat(
      "{\"ack_id\":\"%s\",\"ack_schema_version\":1,\"detail\":%s,\"direction\":\"%s\",\"received_timestamp\":\"%s\",\"signal_id\":\"%s\",\"status\":\"ACK\",\"symbol\":\"%s\"}",
      AckId(sid), detail, direction, NowIso(), sid, symbol);
   BridgeWriteTextAtomic(Path(BR_ACKS, AckName(sid)), UseCommonFolder, json);
   Audit("ack", "ACK", "OK", sid, StringFormat("{\"ack_id\":\"%s\"}", AckId(sid)));
}

//+------------------------------------------------------------------+
//| Write the ONE terminal result and archive the claimed file.       |
//+------------------------------------------------------------------+
void WriteResult(const string sid, const string status, const string reason,
                 const string received, const double sl, const double tp,
                 const long ticket, const double req_price, const double fill_price,
                 const double req_vol, const double fill_vol, const string exec_err,
                 const string extra_detail)
{
   string slippage = "null";
   if(fill_price != 0.0 && req_price != 0.0)
      slippage = StringFormat("%.10g", fill_price - req_price);
   string broker_order_id = (ticket != 0) ? StringFormat("%I64d", ticket) : "null";
   string filled_price    = (fill_price != 0.0) ? StringFormat("%.10g", fill_price) : "null";
   string filled_volume   = (fill_vol   != 0.0) ? StringFormat("%.10g", fill_vol)   : "null";
   string requested_price = (req_price  != 0.0) ? StringFormat("%.10g", req_price)  : "null";
   string requested_vol   = (req_vol    != 0.0) ? StringFormat("%.10g", req_vol)    : "null";
   string sl_s = (sl != 0.0) ? StringFormat("%.10g", sl) : "null";
   string tp_s = (tp != 0.0) ? StringFormat("%.10g", tp) : "null";
   string errj = (StringLen(exec_err) ? exec_err : "null");
   string rid  = ResultId(sid, status);

   string json = StringFormat(
      "{\"broker_order_id\":%s,\"compliance_decision\":null,\"execution_error\":%s,"
      "\"filled_price\":%s,\"filled_volume\":%s,\"processed_timestamp\":\"%s\","
      "\"reason_code\":\"%s\",\"reason_detail\":%s,\"received_timestamp\":\"%s\","
      "\"requested_price\":%s,\"requested_volume\":%s,\"result_id\":\"%s\","
      "\"result_schema_version\":1,\"signal_id\":\"%s\",\"slippage\":%s,"
      "\"status\":\"%s\",\"stop_loss\":%s,\"take_profit\":%s}",
      broker_order_id, errj, filled_price, filled_volume, NowIso(),
      reason, (StringLen(extra_detail) ? extra_detail : "{}"), received,
      requested_price, requested_vol, rid, sid, slippage, status, sl_s, tp_s);

   BridgeWriteTextAtomic(Path(BR_RESULTS, ResultName(sid, status)), UseCommonFolder, json);

   // ledger + archive to the matching family (EXECUTED => accepted)
   string led = StringFormat(
      "{\"processed_timestamp\":\"%s\",\"result_id\":\"%s\",\"signal_id\":\"%s\",\"state\":\"%s\"}",
      NowIso(), rid, sid, status);
   int flags = FILE_READ | FILE_WRITE | FILE_BIN | FILE_SHARE_READ | FILE_SHARE_WRITE;
   if(UseCommonFolder) flags |= FILE_COMMON;
   int h = FileOpen(Path(BR_HEALTH, "dedup.jsonl"), flags);
   if(h != INVALID_HANDLE)
   { FileSeek(h, 0, SEEK_END); uchar b[]; string s = led + "\n";
     int n = StringToCharArray(s, b, 0, WHOLE_ARRAY, CP_UTF8); if(n>0 && b[n-1]==0) n--;
     FileWriteArray(h, b, 0, n); FileFlush(h); FileClose(h); }

   bool accepted = (status == ST_EXECUTED);
   string destdir = accepted ? BR_ACC : BR_REJ;
   BridgeMove(Path(BR_CLAIMED, sid + ".json"), Path(destdir, sid + ".json"), UseCommonFolder);
   Audit("process", status, reason, sid, StringFormat("{\"result_id\":\"%s\"}", rid));
}

//+------------------------------------------------------------------+
//| Quarantine a claimed/pending artifact (fail closed).             |
//+------------------------------------------------------------------+
void Quarantine(const string subdir, const string sid, const string reason)
{
   BridgeMove(Path(subdir, sid + ".json"), Path(BR_QUAR, sid + ".json"), UseCommonFolder);
   Audit("quarantine", "ERROR", reason, sid, "{}");
}

//+------------------------------------------------------------------+
//| Structural + contract validation (mirror bridge/validate.py).     |
//| Returns "" if OK, else a REJECTED/EXPIRED reason code.            |
//+------------------------------------------------------------------+
string ValidateInstruction(const string sid, const uchar &raw[], const int rawlen,
                           const string json, string &symbol, string &direction,
                           double &entry, double &sl, double &tp, double &volume)
{
   bool ok;
   long schema = JsonGetLong(json, "schema_version", ok);
   if(!ok || schema != ALLOW_SCHEMA_VERSION) return "E_SCHEMA";
   if(!VerifyIntegrityDigest(raw, rawlen))    return "E_INTEGRITY";

   // required fields present (schema 3 adds an authoritative ``volume`` — the EA
   // executes it verbatim; session_id/risk_fraction are schema integrity only, the
   // EA never evaluates session time/eligibility nor sizes from risk_fraction)
   string need[] = {"signal_id","session_id","strategy_id","strategy_version","symbol",
                    "direction","entry_price","stop_loss","take_profit","risk_fraction",
                    "volume","generated_timestamp","expiration_timestamp"};
   for(int i = 0; i < ArraySize(need); i++)
      if(StringLen(JsonGet(json, need[i])) == 0) return "E_FIELDS";

   if(JsonGet(json, "strategy_id")      != ALLOW_STRATEGY_ID)      return "E_STRATEGY";
   if(JsonGet(json, "strategy_version") != ALLOW_STRATEGY_VERSION) return "E_STRATEGY";
   if(JsonGet(json, "signal_id")        != sid)                    return "E_ID";

   datetime exp = ParseIsoUtc(JsonGet(json, "expiration_timestamp"));
   datetime gen = ParseIsoUtc(JsonGet(json, "generated_timestamp"));
   datetime now = TimeGMT();
   if(exp == 0 || gen == 0)                 return "E_FIELDS";
   if(now >= exp)                           return "E_EXPIRED";
   if((long)gen - (long)now > FUTURE_SKEW_SEC) return "E_FUTURE";

   symbol = JsonGet(json, "symbol");
   if(StringLen(symbol) != 9 || StringSubstr(symbol, 6, 3) != ".FX") return "E_SYMBOL";

   direction = JsonGet(json, "direction");
   if(direction != "LONG" && direction != "SHORT") return "E_STRUCT";
   entry = JsonGetDouble(json, "entry_price", ok);
   sl    = JsonGetDouble(json, "stop_loss",   ok);
   tp    = JsonGetDouble(json, "take_profit", ok);
   if(entry <= 0 || sl <= 0 || tp <= 0) return "E_STRUCT";
   if(direction == "LONG"  && !(sl < entry && entry < tp)) return "E_STRUCT";
   if(direction == "SHORT" && !(sl > entry && entry > tp)) return "E_STRUCT";
   // M9: authoritative execution volume (transport shape only; broker step/min/max
   // is verified against live symbol metadata in Execute). Missing/non-positive -> reject.
   volume = JsonGetDouble(json, "volume", ok);
   if(!ok || volume <= 0) return "E_STRUCT";
   return "";
}

//+------------------------------------------------------------------+
//| Submit exactly one market order for a validated instruction.      |
//| Writes the ack first, then EXECUTED / EXECUTION_FAILED result.    |
//+------------------------------------------------------------------+
void Execute(const string sid, const string json, const string received)
{
   string symbol, direction; double entry, sl, tp, volume;
   uchar raw[]; int rawlen = 0;
   if(BridgeReadBytes(Path(BR_CLAIMED, sid + ".json"), UseCommonFolder, raw))
      rawlen = ArraySize(raw);

   string vreason = ValidateInstruction(sid, raw, rawlen, json, symbol, direction, entry, sl, tp, volume);
   if(vreason != "")
   {
      string st = (vreason == "E_EXPIRED") ? ST_EXPIRED : ST_REJECTED;
      WriteResult(sid, st, vreason, received, 0, 0, 0, 0, 0, 0, 0, "", "{}");
      return;
   }
   // diagnostic only — the EA logs the originating session but NEVER decides
   // session eligibility (session authority stays upstream in Session Edge).
   Print("Session Edge EA: executing ", sid, " session=", JsonGet(json, "session_id"),
         " ", direction, " ", symbol);

   // No-double-order guard: broker already holds this signal_id -> adopt.
   ulong existing = BrokerTicketByComment(sid);
   if(existing != 0)
   {
      WriteResult(sid, ST_EXECUTED, "X_ADOPTED", received, sl, tp, (long)existing,
                  entry, 0, volume, 0, "",
                  StringFormat("{\"adopted\":true,\"ticket\":%I64d}", existing));
      return;
   }

   WriteAck(sid, symbol, direction);   // ownership accepted -> ack before any order

   // Broker-side input checks (broker constraints, NOT strategy).
   string broker_symbol = NormalizeSymbol(symbol);
   if(broker_symbol == "" || !SymbolSelect(broker_symbol, true))
   { WriteResult(sid, ST_EXECUTION_FAILED, "X_INVALID_SYMBOL", received, sl, tp, 0, entry, 0, volume, 0,
                 StringFormat("{\"symbol\":\"%s\"}", symbol), "{}"); return; }

   // M9: execute the AUTHORITATIVE instruction volume verbatim. Verify EXACT alignment
   // with live broker constraints and REJECT on mismatch — the EA never rounds up or
   // substitutes DefaultVolume (single upstream sizing authority; no EA upsizing).
   double vmin = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(broker_symbol, SYMBOL_VOLUME_STEP);
   double vol = volume;                // authoritative instruction volume (never DefaultVolume)
   if(vol <= 0 || vol < vmin || vol > vmax || (vstep > 0 && MathAbs(MathRound((vol-vmin)/vstep)*vstep + vmin - vol) > vstep*1e-6))
   { WriteResult(sid, ST_EXECUTION_FAILED, "X_INVALID_VOLUME", received, sl, tp, 0, entry, 0, vol, 0,
                 StringFormat("{\"volume\":%.10g}", vol), "{}"); return; }

   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   { WriteResult(sid, ST_EXECUTION_FAILED, "X_DISCONNECTED", received, sl, tp, 0, entry, 0, vol, 0,
                 "{\"execution_error\":\"terminal_disconnected\"}", "{}"); return; }

   g_trade.SetExpertMagicNumber(MagicNumber);
   bool sent = (direction == "LONG")
      ? g_trade.Buy(vol, broker_symbol, 0.0, sl, tp, sid)
      : g_trade.Sell(vol, broker_symbol, 0.0, sl, tp, sid);
   uint retcode = g_trade.ResultRetcode();

   if(!sent || retcode != TRADE_RETCODE_DONE)
   {
      string xr = MapRetcode(retcode);
      string err = StringFormat("{\"retcode\":%u,\"comment\":\"%s\"}",
                                retcode, g_trade.ResultRetcodeDescription());
      WriteResult(sid, ST_EXECUTION_FAILED, xr, received, sl, tp, 0, entry, 0, vol, 0, err, "{}");
      return;
   }

   ulong ticket = g_trade.ResultOrder();
   double fill  = g_trade.ResultPrice();
   double fvol  = g_trade.ResultVolume();
   WriteResult(sid, ST_EXECUTED, "X_OK", received, sl, tp, (long)ticket,
               entry, fill, vol, fvol, "",
               StringFormat("{\"ticket\":%I64d,\"symbol\":\"%s\",\"direction\":\"%s\"}",
                            ticket, symbol, direction));
}

//+------------------------------------------------------------------+
//| Map an MT5 retcode to a deterministic execution reason code.      |
//+------------------------------------------------------------------+
string MapRetcode(const uint rc)
{
   switch(rc)
   {
      case TRADE_RETCODE_REJECT:        return "X_BROKER_REJECT";
      case TRADE_RETCODE_MARKET_CLOSED: return "X_MARKET_CLOSED";
      case TRADE_RETCODE_REQUOTE:       return "X_REQUOTE";
      case TRADE_RETCODE_PRICE_OFF:     return "X_OFF_QUOTES";
      case TRADE_RETCODE_PRICE_CHANGED: return "X_OFF_QUOTES";
      case TRADE_RETCODE_TOO_MANY_REQUESTS: return "X_TRADE_BUSY";
      case TRADE_RETCODE_TIMEOUT:       return "X_TRADE_BUSY";
      case TRADE_RETCODE_INVALID_VOLUME:return "X_INVALID_VOLUME";
      case TRADE_RETCODE_INVALID_STOPS: return "X_INVALID_STOPS";
      case TRADE_RETCODE_NO_MONEY:      return "X_NO_MONEY";
      case TRADE_RETCODE_CONNECTION:    return "X_DISCONNECTED";
      case TRADE_RETCODE_TRADE_DISABLED:return "X_MARKET_CLOSED";
      default:                          return "X_BROKER_ERROR";
   }
}

//+------------------------------------------------------------------+
//| Claim + process the next pending instruction (single pass).       |
//+------------------------------------------------------------------+
bool ProcessNext()
{
   string name; long h = FileFindFirst(Path(BR_PENDING, "*.json"), name,
                                       (UseCommonFolder ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE) return false;
   bool done = false;
   do
   {
      if(StringLen(name) != 21) continue;          // 16 hex + ".json"
      string sid = StringSubstr(name, 0, 16);
      if(BridgeClaim(Path(BR_PENDING, name), Path(BR_CLAIMED, name), UseCommonFolder))
      {
         Audit("claim", "CLAIMED", "OK", sid, "{}");
         ProcessClaimed(sid);
         done = true;
         break;
      }
   } while(FileFindNext(h, name));
   FileFindClose(h);
   return done;
}

//+------------------------------------------------------------------+
//| Process one already-claimed instruction (dedup then execute).     |
//+------------------------------------------------------------------+
void ProcessClaimed(const string sid)
{
   string family;
   if(SeenTerminal(sid, family))                   // already terminal -> adopt, no 2nd order
   {
      string destdir = (family == "ACCEPTED") ? BR_ACC : BR_REJ;
      BridgeMove(Path(BR_CLAIMED, sid + ".json"), Path(destdir, sid + ".json"), UseCommonFolder);
      Audit("process", ST_DUPLICATE, "E_DUP", sid, "{\"adopted\":true}");
      return;
   }
   string received = NowIso();
   string json;
   if(!BridgeReadText(Path(BR_CLAIMED, sid + ".json"), UseCommonFolder, json))
   { Quarantine(BR_CLAIMED, sid, "E_SERDE"); return; }
   Execute(sid, json, received);
}

//+------------------------------------------------------------------+
//| Broker-aware restart recovery. Never submits a second order.      |
//+------------------------------------------------------------------+
void Recover()
{
   string name; long h = FileFindFirst(Path(BR_CLAIMED, "*.json"), name,
                                       (UseCommonFolder ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE) { Audit("reconcile", "EXEC_DONE", "OK", "", "{}"); return; }
   do
   {
      if(StringLen(name) != 21) { Quarantine(BR_CLAIMED, StringSubstr(name,0,16), "E_UNSAFE_PATH"); continue; }
      string sid = StringSubstr(name, 0, 16);
      string family;
      if(SeenTerminal(sid, family))
      {
         string destdir = (family == "ACCEPTED") ? BR_ACC : BR_REJ;
         BridgeMove(Path(BR_CLAIMED, sid + ".json"), Path(destdir, sid + ".json"), UseCommonFolder);
         Audit("reconcile", ST_DUPLICATE, "ADOPTED", sid, "{}");
         continue;
      }
      ulong ticket = BrokerTicketByComment(sid);   // broker truth
      if(ticket != 0)
      {
         // crash after OrderSend, before result -> finalize EXECUTED, no resend
         string json; BridgeReadText(Path(BR_CLAIMED, sid + ".json"), UseCommonFolder, json);
         bool ok; double sl = JsonGetDouble(json, "stop_loss", ok);
         double tp = JsonGetDouble(json, "take_profit", ok);
         double entry = JsonGetDouble(json, "entry_price", ok);
         double fill = PositionGetDouble(POSITION_PRICE_OPEN);
         double vol  = PositionGetDouble(POSITION_VOLUME);
         WriteResult(sid, ST_EXECUTED, "X_RECONCILE", NowIso(), sl, tp, (long)ticket,
                     entry, fill, vol, vol, "",
                     StringFormat("{\"ticket\":%I64d,\"recovered\":true}", ticket));
      }
      else if(BridgeExists(Path(BR_ACKS, AckName(sid)), UseCommonFolder))
      {
         // ack present, no broker position -> outcome unknown -> fail closed
         Audit("reconcile", "RECONCILIATION_REQUIRED", "RECONCILIATION_REQUIRED", sid, "{}");
      }
      else
      {
         ProcessClaimed(sid);                       // never attempted -> safe
      }
   } while(FileFindNext(h, name));
   FileFindClose(h);
   Audit("reconcile", "EXEC_DONE", "OK", "", "{}");
}

//+------------------------------------------------------------------+
int OnInit()
{
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))
   {
      Print("Session Edge EA: automated trading is not allowed. Enable it and reload.");
      return INIT_FAILED;
   }
   // The bridge tree must already exist (the strategy engine/producer owns it).
   if(!BridgeExists(Path(BR_PENDING, ""), UseCommonFolder) &&
      !BridgeExists(BridgeRoot + "\\outbox", UseCommonFolder))
      Print("Session Edge EA: bridge_root '", BridgeRoot, "' not found under the terminal Files folder.");
   EventSetTimer(MathMax(1, PollSeconds));
   Print("Session Edge Execution Adapter initialised. bridge_root=", BridgeRoot);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnTimer()
{
   if(!g_recovered)                    // reconstruct state from bridge + terminal
   {
      Recover();
      ManageRecover();                 // Phase 7B-B: reconcile any claimed manage instruction
      g_recovered = true;
   }
   ProcessNext();                      // at most one entry claim+execute per tick
   ManageProcessNext();               // Phase 7B-B: at most one manage claim+apply per tick
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
//| OnTick is intentionally empty: this EA is event/timer driven and  |
//| never reads price series or reacts to quotes (no strategy logic). |
//+------------------------------------------------------------------+
void OnTick() { }

//+------------------------------------------------------------------+
//| Phase 7B-B manage-channel applier (additive). Included AFTER all  |
//| globals (g_trade, BridgeRoot, UseCommonFolder) and helpers        |
//| (NowIso, Sha256Hex16, JsonBridge) are declared, so its functions  |
//| resolve. Entry execution behavior above is unchanged.             |
//+------------------------------------------------------------------+
#include "SessionEdgeManageHandler.mqh"
//+------------------------------------------------------------------+

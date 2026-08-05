//+------------------------------------------------------------------+
//| SessionEdgeManageHandler.mqh                                     |
//| Session Edge - MT5 manage-channel handler (Phase 7B-B, Option C) |
//|                                                                  |
//| THIN, BOUNDED-AUTHORITY stop-management applier. It is the       |
//| terminal-side mirror of the accepted offline reference in         |
//| forex_swing_orb/manage/consumer.py (ManageConsumer): that offline |
//| reference is the authoritative, unit-tested behavior; this file   |
//| applies the identical 18-step validation in MQL5. It NEVER opens  |
//| a trade, reverses direction, changes take-profit, loosens or     |
//| removes a stop. The strategy-side Position Manager is the sole    |
//| decision-maker; this file only applies a validated MANAGE_STOP or |
//| PROTECTIVE_CLOSE. No strategy logic, no networking, no shell-out.  |
//|                                                                  |
//| NOTE: like SessionEdgeExecutionEA.mq5 this is compiled only in    |
//| MetaEditor on Windows; it is not compiled in the project CI.      |
//+------------------------------------------------------------------+
#property strict
// This header is included by SessionEdgeExecutionEA.mq5 AFTER JsonBridge.mqh and
// after g_trade / BridgeRoot / UseCommonFolder / NowIso / Sha256Hex16 are declared;
// it deliberately does NOT re-include JsonBridge.mqh (that header has no include
// guard, so a second include would duplicate its definitions).

//--- manage sub-paths (mirror forex_swing_orb/manage/paths.py) -------
#define MG_PENDING   "manage\\outbox\\pending\\"
#define MG_CLAIMED   "manage\\outbox\\claimed\\"
#define MG_RESULTS   "manage\\inbox\\results\\"
#define MG_ARC_APP   "manage\\archive\\applied\\"
#define MG_ARC_REJ   "manage\\archive\\rejected\\"
#define MG_ARC_CLO   "manage\\archive\\closed\\"
#define MG_QUAR      "manage\\quarantine\\"
#define MG_HEALTH    "manage\\health\\"

#define MG_SCHEMA_VERSION 1

//+------------------------------------------------------------------+
string MgPath(const string sub, const string name) { return BridgeRoot + "\\" + sub + name; }

//+------------------------------------------------------------------+
//| Tick-space equality on the symbol grid (mirror manage/ticks.py). |
//+------------------------------------------------------------------+
bool MgEqStop(const string symbol, const double a, const double b)
{
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0) point = 0.00001;
   long ta = (long)MathRound(a / point);
   long tb = (long)MathRound(b / point);
   return (ta == tb);
}

//+------------------------------------------------------------------+
//| Write ONE terminal MANAGE_RESULT and archive the claimed file.    |
//+------------------------------------------------------------------+
void MgWriteResult(const string mid, const string sid, const long ticket,
                   const string symbol, const string action, const string status,
                   const string reason, const uint retcode,
                   const double reqStop, const double expStop,
                   const double before, const double after, const long seq,
                   const string archdir)
{
   string reconc = "TERMINAL";
   string json = StringFormat(
      "{\"action\":\"%s\",\"applied_timestamp\":%s,\"broker_message\":\"\","
      "\"broker_retcode\":%u,\"claimed_timestamp\":\"%s\",\"completed_timestamp\":\"%s\","
      "\"expected_current_stop\":%s,\"manage_id\":\"%s\",\"observed_stop_after\":%s,"
      "\"observed_stop_before\":%s,\"per_ticket_sequence\":%I64d,\"reason_code\":\"%s\","
      "\"reconciliation_state\":\"%s\",\"requested_stop\":%s,\"schema_version\":%d,"
      "\"signal_id\":\"%s\",\"status\":\"%s\",\"symbol\":\"%s\",\"ticket\":%I64d}",
      action, (status=="APPLIED"||status=="ALREADY_APPLIED") ? StringFormat("\"%s\"",NowIso()) : "null",
      retcode, NowIso(), NowIso(),
      (expStop!=0.0)?StringFormat("%.10g",expStop):"null", mid,
      (after!=0.0)?StringFormat("%.10g",after):"null",
      (before!=0.0)?StringFormat("%.10g",before):"null", seq, reason,
      reconc, (reqStop!=0.0)?StringFormat("%.10g",reqStop):"null", MG_SCHEMA_VERSION,
      sid, status, symbol, ticket);
   string rid = StringSubstr(Sha256Hex16(json), 0, 16);
   BridgeWriteTextAtomic(MgPath(MG_RESULTS, mid + "." + rid + ".json"), UseCommonFolder, json);
   BridgeMove(MgPath(MG_CLAIMED, mid + ".json"), MgPath(archdir, mid + ".json"), UseCommonFolder);
}

//+------------------------------------------------------------------+
//| Apply one claimed manage instruction (18-step, stop on first fail)|
//+------------------------------------------------------------------+
void MgProcessClaimed(const string mid)
{
   string json;
   if(!BridgeReadText(MgPath(MG_CLAIMED, mid + ".json"), UseCommonFolder, json))
   { BridgeMove(MgPath(MG_CLAIMED, mid+".json"), MgPath(MG_QUAR, mid+".json"), UseCommonFolder); return; }

   // 2/3 schema + digest
   bool ok;
   if(JsonGetLong(json, "schema_version", ok) != MG_SCHEMA_VERSION || !ok)
   { MgWriteResult(mid,"","0","","","REJECTED_INVALID","schema",0,0,0,0,0,0,MG_ARC_REJ); return; }
   uchar raw[]; int n=0;
   if(BridgeReadBytes(MgPath(MG_CLAIMED, mid+".json"), UseCommonFolder, raw)) n=ArraySize(raw);
   if(!VerifyIntegrityDigest(raw, n))
   { MgWriteResult(mid,"","0","","","REJECTED_INVALID","digest",0,0,0,0,0,0,MG_ARC_REJ); return; }

   string sid    = JsonGet(json, "signal_id");
   long   ticket = JsonGetLong(json, "ticket", ok);
   string symbol = JsonGet(json, "symbol");
   string dirn   = JsonGet(json, "direction");
   string action = JsonGet(json, "action");
   long   seq    = JsonGetLong(json, "per_ticket_sequence", ok);
   double target = JsonGetDouble(json, "target_stop", ok);
   double expect = JsonGetDouble(json, "expected_current_stop", ok);
   double mref   = JsonGetDouble(json, "market_reference", ok);
   double mind   = JsonGetDouble(json, "broker_min_stop_distance", ok);

   // 5 expiry
   datetime exp = ParseIsoUtc(JsonGet(json, "expiration_timestamp"));
   if(exp == 0 || TimeGMT() >= exp)
   { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_EXPIRED","expired",0,target,expect,0,0,seq,MG_ARC_REJ); return; }

   // 14 connectivity, 7 position open
   if(!TerminalInfoInteger(TERMINAL_CONNECTED))
   { return; }                                   // non-terminal: leave for recovery
   if(!PositionSelectByTicket(ticket))
   { string st=(action=="PROTECTIVE_CLOSE")?"NO_OP_CLOSED":"NO_POSITION";
     MgWriteResult(mid,sid,ticket,symbol,action,st,"no_position",0,target,expect,0,0,seq,MG_ARC_CLO); return; }

   // 6 symbol/direction match
   string posSym = PositionGetString(POSITION_SYMBOL);
   long   posTyp = PositionGetInteger(POSITION_TYPE);
   string posDir = (posTyp == POSITION_TYPE_BUY) ? "LONG" : "SHORT";
   if(posSym != symbol || posDir != dirn)
   { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_INVALID","identity",0,target,expect,0,0,seq,MG_ARC_REJ); return; }

   double before = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);

   if(action == "PROTECTIVE_CLOSE")
   {
      // R3: independently authorize the close against the frozen PMReason set.
      string preason = JsonGet(json, "pm_reason");
      if(preason != "PM_KILL_SWITCH" && preason != "PM_WEEKEND_EXIT" &&
         preason != "PM_MAX_DURATION_EXIT")
      { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_INVALID","unauthorized_close",
                      0,0,expect,before,0,seq,MG_ARC_REJ); return; }
      if(g_trade.PositionClose(ticket))
         MgWriteResult(mid,sid,ticket,symbol,action,"NO_OP_CLOSED","closed",
                       g_trade.ResultRetcode(),0,expect,before,0,seq,MG_ARC_CLO);
      else
         MgWriteResult(mid,sid,ticket,symbol,action,"BROKER_REJECTED","close_failed",
                       g_trade.ResultRetcode(),0,expect,before,0,seq,MG_ARC_REJ);
      return;
   }

   // ---- MODIFY_STOP ----
   // 10 compare-and-swap against the LIVE broker stop
   if(!MgEqStop(symbol, before, expect))
   { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_STALE","cas",0,target,expect,before,0,seq,MG_ARC_REJ); return; }
   // 11 tick normalization
   double q = NormalizeDouble(target, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
   // 12 risk-reducing-only (never loosen)
   bool legal = (dirn == "LONG") ? (q >= before) : (q <= before);
   if(!legal)
   { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_LOOSEN","loosen",0,q,expect,before,0,seq,MG_ARC_REJ); return; }
   // 13 broker min-stop / freeze distance
   if(mind > 0 && mref != 0.0 && MathAbs(q - mref) < mind)
   { MgWriteResult(mid,sid,ticket,symbol,action,"REJECTED_BROKER_CONSTRAINT","min_stop",0,q,expect,before,0,seq,MG_ARC_REJ); return; }
   // 15 apply (never touches TP)
   if(!g_trade.PositionModify(ticket, q, tp))
   { uint rc=g_trade.ResultRetcode();
     string st=(rc==TRADE_RETCODE_INVALID_STOPS||rc==TRADE_RETCODE_REJECT)?"REJECTED_BROKER_CONSTRAINT":"BROKER_REJECTED";
     MgWriteResult(mid,sid,ticket,symbol,action,st,"broker",rc,q,expect,before,0,seq,MG_ARC_REJ); return; }
   // 16 broker read-back verification
   if(!PositionSelectByTicket(ticket)) return;   // uncertain: leave for recovery
   double after = PositionGetDouble(POSITION_SL);
   if(!MgEqStop(symbol, after, q)) return;        // uncertain: leave for recovery
   // 17/18 terminal result + archive
   MgWriteResult(mid,sid,ticket,symbol,action,"APPLIED","ok",
                 g_trade.ResultRetcode(),q,expect,before,after,seq,MG_ARC_APP);
}

//+------------------------------------------------------------------+
//| Claim + process the next pending manage instruction (single pass).|
//+------------------------------------------------------------------+
bool ManageProcessNext()
{
   string name; long h = FileFindFirst(MgPath(MG_PENDING, "*.json"), name,
                                       (UseCommonFolder ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE) return false;
   bool done = false;
   do
   {
      if(StringLen(name) != 21) continue;             // 16 hex + ".json"
      string mid = StringSubstr(name, 0, 16);
      if(BridgeClaim(MgPath(MG_PENDING, name), MgPath(MG_CLAIMED, name), UseCommonFolder))
      { MgProcessClaimed(mid); done = true; break; }
   } while(FileFindNext(h, name));
   FileFindClose(h);
   return done;
}

//+------------------------------------------------------------------+
//| Recovery: re-evaluate any claimed manage instruction (crash-safe).|
//| If the broker stop already equals target -> ALREADY_APPLIED.      |
//+------------------------------------------------------------------+
void ManageRecover()
{
   string name; long h = FileFindFirst(MgPath(MG_CLAIMED, "*.json"), name,
                                       (UseCommonFolder ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE) return;
   do
   {
      if(StringLen(name) != 21) continue;
      string mid = StringSubstr(name, 0, 16);
      string json;
      if(!BridgeReadText(MgPath(MG_CLAIMED, mid+".json"), UseCommonFolder, json)) continue;
      bool ok; long ticket = JsonGetLong(json, "ticket", ok);
      string symbol = JsonGet(json, "symbol");
      double target = JsonGetDouble(json, "target_stop", ok);
      if(JsonGet(json,"action")=="MODIFY_STOP" && PositionSelectByTicket(ticket))
      {
         double after = PositionGetDouble(POSITION_SL);
         if(MgEqStop(symbol, after, NormalizeDouble(target,(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS))))
         {
            long seq = JsonGetLong(json,"per_ticket_sequence",ok);
            MgWriteResult(mid, JsonGet(json,"signal_id"), ticket, symbol, "MODIFY_STOP",
                          "ALREADY_APPLIED","recovered",0,target,
                          JsonGetDouble(json,"expected_current_stop",ok),0,after,seq,MG_ARC_APP);
            continue;
         }
      }
      MgProcessClaimed(mid);                          // else re-run full validation
   } while(FileFindNext(h, name));
   FileFindClose(h);
}
//+------------------------------------------------------------------+

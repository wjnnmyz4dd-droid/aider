//+------------------------------------------------------------------+
//| JsonBridge.mqh                                                    |
//| Session Edge MT5 Execution Adapter - bridge I/O + JSON + digest.  |
//|                                                                    |
//| Helper routines for the execution adapter EA. NO strategy logic,  |
//| NO indicators, NO price-series access, NO networking. Only:       |
//|   * filesystem access to the bridge tree (sandboxed MQL5 files)   |
//|   * minimal JSON scalar extraction over the bridge's canonical    |
//|     JSON (sorted keys, compact separators - see bridge/serialize) |
//|   * SHA-256 (CryptEncode) integrity-digest verification           |
//|                                                                    |
//| Digest verification is TEXTUAL and byte-exact: the producer wrote |
//| canonical_json(record_with_digest); the digest is                 |
//| sha256(canonical_json(record_without_digest)). Because keys are   |
//| sorted and compact, deleting the "integrity_digest" member from   |
//| the raw file bytes reproduces the without-digest bytes EXACTLY -   |
//| so we never reformat numbers and cannot drift from the producer.  |
//+------------------------------------------------------------------+
#property strict

//--- fixed bridge sub-paths (mirror forex_swing_orb/bridge/paths.py)
#define BR_PENDING   "outbox\\pending\\"
#define BR_CLAIMED   "outbox\\claimed\\"
#define BR_RESULTS   "inbox\\results\\"
#define BR_ACKS      "inbox\\acks\\"
#define BR_ACC       "archive\\accepted\\"
#define BR_REJ       "archive\\rejected\\"
#define BR_QUAR      "quarantine\\"
#define BR_HEALTH    "health\\"

//+------------------------------------------------------------------+
//| Read an entire file as raw bytes (byte-exact; for digest + parse).|
//| Returns false if the file cannot be opened. common=FILE_COMMON.   |
//+------------------------------------------------------------------+
bool BridgeReadBytes(const string relpath, const bool common, uchar &out[])
{
   int flags = FILE_READ | FILE_BIN | FILE_SHARE_READ;
   if(common) flags |= FILE_COMMON;
   int h = FileOpen(relpath, flags);
   if(h == INVALID_HANDLE)
      return false;
   ulong sz = FileSize(h);
   ArrayResize(out, (int)sz);
   if(sz > 0)
      FileReadArray(h, out, 0, (int)sz);
   FileClose(h);
   return true;
}

//+------------------------------------------------------------------+
//| Read a file as a UTF-8 string.                                    |
//+------------------------------------------------------------------+
bool BridgeReadText(const string relpath, const bool common, string &out)
{
   uchar bytes[];
   if(!BridgeReadBytes(relpath, common, bytes))
      return false;
   out = CharArrayToString(bytes, 0, WHOLE_ARRAY, CP_UTF8);
   return true;
}

//+------------------------------------------------------------------+
//| Atomic write: write to a temp name, then FileMove into place.     |
//| MQL5 has no fsync; FileFlush + rename is the strongest guarantee. |
//+------------------------------------------------------------------+
bool BridgeWriteTextAtomic(const string relpath, const bool common, const string text)
{
   string tmp = relpath + ".tmp";
   int flags = FILE_WRITE | FILE_BIN | FILE_SHARE_READ | FILE_SHARE_WRITE;
   if(common) flags |= FILE_COMMON;
   int h = FileOpen(tmp, flags);
   if(h == INVALID_HANDLE)
      return false;
   uchar bytes[];
   int n = StringToCharArray(text, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0 && bytes[n-1] == 0) n--;             // drop the terminating NUL
   if(n > 0)
      FileWriteArray(h, bytes, 0, n);
   FileFlush(h);
   FileClose(h);
   int mflags = (common ? FILE_COMMON : 0);
   // FILE_REWRITE: result/ack/archive writes are deterministic (same bytes) so
   // replacing an identical prior artifact is safe and idempotent.
   if(!FileMove(tmp, mflags, relpath, mflags | FILE_REWRITE))
   {
      FileDelete(tmp, mflags);
      return false;
   }
   return true;
}

//+------------------------------------------------------------------+
//| Exclusive claim: FileMove WITHOUT FILE_REWRITE fails if the       |
//| destination already exists -> the winning move IS the claim.      |
//+------------------------------------------------------------------+
bool BridgeClaim(const string src_rel, const string dst_rel, const bool common)
{
   int mflags = (common ? FILE_COMMON : 0);
   return FileMove(src_rel, mflags, dst_rel, mflags);   // no FILE_REWRITE => exclusive
}

bool BridgeMove(const string src_rel, const string dst_rel, const bool common)
{
   int mflags = (common ? FILE_COMMON : 0);
   return FileMove(src_rel, mflags, dst_rel, mflags | FILE_REWRITE);
}

bool BridgeExists(const string relpath, const bool common)
{
   return FileIsExist(relpath, (common ? FILE_COMMON : 0));
}

//+------------------------------------------------------------------+
//| Robust DIRECTORY-existence probe. FileIsExist() is documented to  |
//| check a FILE; on a directory path its result is build-dependent   |
//| (commonly false), which made the OnInit bridge probe warn         |
//| spuriously. FileFindFirst enumerates the sandbox and returns a    |
//| valid handle when the directory contains ANY entry (file OR        |
//| subfolder), so it detects a producer-initialized bridge tree      |
//| deterministically. ``reldir`` must end with a backslash.          |
//+------------------------------------------------------------------+
bool BridgeDirHasEntries(const string reldir, const bool common)
{
   string name;
   long h = FileFindFirst(reldir + "*", name, (common ? FILE_COMMON : 0));
   if(h == INVALID_HANDLE)
      return false;
   FileFindClose(h);
   return true;
}

//+------------------------------------------------------------------+
//| Minimal JSON string escaper for values the EA emits into a JSON   |
//| beacon (e.g. the Windows data_path, which contains backslashes).  |
//| Canonical JSON is ensure_ascii=False, so only '\' and '"' need    |
//| escaping; backslash MUST be replaced first.                       |
//+------------------------------------------------------------------+
string JsonEscape(const string s)
{
   string out = s;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   return out;
}

//+------------------------------------------------------------------+
//| SHA-256 of a byte range -> lowercase hex (64 chars).              |
//+------------------------------------------------------------------+
string Sha256Hex(const uchar &data[], const int count)
{
   uchar src[]; ArrayResize(src, count);
   for(int i = 0; i < count; i++) src[i] = data[i];
   uchar key[];                       // empty key for a plain hash
   uchar hash[];
   int n = CryptEncode(CRYPT_HASH_SHA256, src, key, hash);
   if(n <= 0)
      return "";
   string hex = "";
   for(int i = 0; i < n; i++)
      hex += StringFormat("%02x", hash[i]);
   return hex;
}

//+------------------------------------------------------------------+
//| Extract a scalar JSON value token for a top-level key from        |
//| canonical JSON (compact, no spaces). Returns "" if absent.        |
//| For strings the surrounding quotes are stripped; numbers/bools    |
//| are returned as their literal text.                               |
//+------------------------------------------------------------------+
string JsonGet(const string json, const string key)
{
   string needle = "\"" + key + "\":";
   int p = StringFind(json, needle);
   if(p < 0)
      return "";
   int v = p + StringLen(needle);
   int len = StringLen(json);
   if(v >= len)
      return "";
   ushort c = StringGetCharacter(json, v);
   if(c == '"')                                   // string value
   {
      int start = v + 1;
      int i = start;
      while(i < len)
      {
         ushort ch = StringGetCharacter(json, i);
         if(ch == '\\') { i += 2; continue; }     // skip escaped char
         if(ch == '"') break;
         i++;
      }
      return StringSubstr(json, start, i - start);
   }
   // number / bool / null: read until , } ]
   int i = v;
   while(i < len)
   {
      ushort ch = StringGetCharacter(json, i);
      if(ch == ',' || ch == '}' || ch == ']') break;
      i++;
   }
   return StringSubstr(json, v, i - v);
}

double JsonGetDouble(const string json, const string key, bool &ok)
{
   string t = JsonGet(json, key);
   ok = (StringLen(t) > 0);
   return ok ? (double)StringToDouble(t) : 0.0;
}

long JsonGetLong(const string json, const string key, bool &ok)
{
   string t = JsonGet(json, key);
   ok = (StringLen(t) > 0);
   return ok ? (long)StringToInteger(t) : 0;
}

//+------------------------------------------------------------------+
//| Verify the integrity digest textually and byte-exactly.          |
//| raw = exact file bytes; returns true iff                          |
//|   sha256(bytes_without_integrity_digest_member) == claimed hex.   |
//+------------------------------------------------------------------+
bool VerifyIntegrityDigest(const uchar &raw[], const int rawlen)
{
   string json = CharArrayToString(raw, 0, rawlen, CP_UTF8);
   string claimed = JsonGet(json, "integrity_digest");
   if(StringLen(claimed) != 64)
      return false;

   // Locate the full member `"integrity_digest":"<hex>"` in the text.
   string member_key = "\"integrity_digest\":\"";
   int kp = StringFind(json, member_key);
   if(kp < 0)
      return false;
   int val_start = kp + StringLen(member_key);
   int val_end = val_start + 64;                  // 64 hex chars
   if(val_end >= StringLen(json))
      return false;
   int member_start = kp;
   int member_end = val_end + 1;                  // include closing quote

   // Delete the member and exactly one adjacent comma so the remaining bytes
   // equal canonical_json(record_without_digest). Sorted keys => the member is
   // either preceded by ',' (last member) or followed by ',' (otherwise).
   string body;
   ushort before = (member_start > 0) ? StringGetCharacter(json, member_start-1) : 0;
   ushort after  = (member_end < StringLen(json)) ? StringGetCharacter(json, member_end) : 0;
   if(after == ',')
      body = StringSubstr(json, 0, member_start) + StringSubstr(json, member_end + 1);
   else if(before == ',')
      body = StringSubstr(json, 0, member_start - 1) + StringSubstr(json, member_end);
   else
      body = StringSubstr(json, 0, member_start) + StringSubstr(json, member_end);

   uchar bodybytes[];
   int n = StringToCharArray(body, bodybytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(n > 0 && bodybytes[n-1] == 0) n--;
   string computed = Sha256Hex(bodybytes, n);
   return (computed == claimed);
}

//+------------------------------------------------------------------+
//| ISO-8601 'Z' timestamp -> datetime (UTC). Returns 0 on parse err. |
//+------------------------------------------------------------------+
datetime ParseIsoUtc(const string iso)
{
   if(StringLen(iso) < 19)
      return 0;
   string s = iso;
   StringReplace(s, "T", " ");
   StringReplace(s, "Z", "");
   return StringToTime(StringSubstr(s, 0, 19));   // "YYYY-MM-DD HH:MM:SS"
}
//+------------------------------------------------------------------+

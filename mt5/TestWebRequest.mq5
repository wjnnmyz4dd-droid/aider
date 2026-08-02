//+------------------------------------------------------------------+
//| TestWebRequest.mq5                                              |
//| Throwaway diagnostic script -- NOT part of Titan Protocol.       |
//| Purpose: isolate whether WebRequest() works at all in a given    |
//| terminal for an external allow-listed URL, independent of the   |
//| Titan Bridge (127.0.0.1:8787). Attach forexfactory.com (or any   |
//| already-allow-listed external URL) to the terminal's WebRequest  |
//| allow-list first, then run this script and check the Experts     |
//| log for the TEST WebRequest line it prints.                     |
//+------------------------------------------------------------------+
#property strict

void OnStart()
  {
   string headers = "";
   string result_headers = "";
   char post[];
   char result[];

   uint startTick = GetTickCount();
   ResetLastError();
   int status = WebRequest("GET", "http://www.forexfactory.com", headers, 5000, post, result, result_headers);
   int err = GetLastError();
   uint elapsed = GetTickCount() - startTick;

   Print("TEST WebRequest status=", status, " GetLastError=", err, " elapsedMs=", elapsed);
  }
//+------------------------------------------------------------------+

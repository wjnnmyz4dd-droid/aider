"""Unit tests for the completed trade journal (phantom_institutional).

Covers the PHANTOM ANALYTICS PHASE requirements: the journal appender writes the
canonical schema (original 6 columns first, then the 8 analytics fields), is
backward compatible with an older 6-column journal (in-place header migration,
old rows backfilled blank), and never estimates a missing value (stores blank).

Run under an env with flask+numpy+requests available:

    python -m unittest tests.test_journal_fields

Importing phantom_institutional writes a startup log to ~/Documents, so we
ensure that directory exists first (it exists on the target Windows VPS).
"""

import os
os.makedirs(os.path.join(os.path.expanduser("~"), "Documents"), exist_ok=True)

import csv
import tempfile
import unittest

import phantom_institutional as P


OLD_FIELDS = ["won", "profit", "session", "setup", "symbol", "ts"]


class TestJournalFields(unittest.TestCase):
    def setUp(self):
        # redirect the journal to a throwaway file; never touch real data
        self._saved = P.JOURNAL_FILE
        self._tmp = tempfile.mktemp(suffix=".csv")
        P.JOURNAL_FILE = self._tmp

    def tearDown(self):
        P.JOURNAL_FILE = self._saved
        if os.path.isfile(self._tmp):
            os.remove(self._tmp)

    def _read(self):
        with open(self._tmp, newline="") as f:
            rows = list(csv.DictReader(f))
            f.seek(0)
            header = next(csv.reader(f), [])
        return header, rows

    # --- canonical schema: original 6 columns first, analytics appended ---
    def test_schema_order_backward_compatible(self):
        self.assertEqual(P.JOURNAL_FIELDS[:6], OLD_FIELDS)
        self.assertEqual(
            P.JOURNAL_FIELDS[6:],
            ["score", "regime", "r_multiple", "entry_price",
             "stop_loss", "take_profit", "direction", "trade_id"],
        )

    # --- fresh file gets the full header immediately ---
    def test_fresh_file_full_header(self):
        P._append_journal({
            "won": 1, "profit": 1.0, "session": "NY", "setup": "ORB",
            "symbol": "EURUSD", "ts": "t", "score": 80.0, "regime": "BREAKOUT",
            "r_multiple": 1.5, "entry_price": 1.1, "stop_loss": 1.09,
            "take_profit": 1.12, "direction": "BUY", "trade_id": "x1",
        })
        header, rows = self._read()
        self.assertEqual(header, P.JOURNAL_FIELDS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trade_id"], "x1")

    # --- an old 6-column journal migrates in place, old rows preserved ---
    def test_migrates_old_journal(self):
        with open(self._tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=OLD_FIELDS)
            w.writeheader()
            w.writerow({"won": "1", "profit": "12.5", "session": "LONDON",
                        "setup": "BOS", "symbol": "EURUSD",
                        "ts": "2026-01-01T00:00:00"})
            w.writerow({"won": "0", "profit": "-8.0", "session": "NY",
                        "setup": "FVG", "symbol": "GBPUSD",
                        "ts": "2026-01-02T00:00:00"})

        P._append_journal({
            "won": 1, "profit": 30.0, "session": "NY", "setup": "ORB",
            "symbol": "USDJPY", "ts": "2026-07-02T12:00:00", "score": 74.82,
            "regime": "TRENDING_UP", "r_multiple": 2.0, "entry_price": 156.10,
            "stop_loss": 155.90, "take_profit": 156.50, "direction": "BUY",
            "trade_id": "abc-123",
        })

        header, rows = self._read()
        self.assertEqual(header, P.JOURNAL_FIELDS)
        self.assertEqual(len(rows), 3)  # 2 legacy + 1 new
        legacy = rows[0]
        self.assertEqual(legacy["symbol"], "EURUSD")
        self.assertEqual(legacy["profit"], "12.5")
        for col in P.JOURNAL_FIELDS[6:]:
            self.assertEqual(legacy[col], "", f"legacy {col} not blank")
        new = rows[2]
        self.assertEqual(new["score"], "74.82")
        self.assertEqual(new["regime"], "TRENDING_UP")
        self.assertEqual(new["r_multiple"], "2.0")
        self.assertEqual(new["direction"], "BUY")
        self.assertEqual(new["trade_id"], "abc-123")

    # --- missing values are stored blank, never estimated ---
    def test_missing_values_blank_never_estimated(self):
        P._append_journal({
            "won": 0, "profit": -5.0, "session": "ASIA", "setup": "BOS",
            "symbol": "AUDUSD", "ts": "t", "score": None, "regime": None,
            "r_multiple": None, "entry_price": None, "stop_loss": None,
            "take_profit": None, "direction": None, "trade_id": None,
        })
        _, rows = self._read()
        row = rows[-1]
        for col in ["score", "regime", "r_multiple", "entry_price",
                    "stop_loss", "take_profit", "direction", "trade_id"]:
            self.assertEqual(row[col], "", f"{col} should be blank")


if __name__ == "__main__":
    unittest.main()

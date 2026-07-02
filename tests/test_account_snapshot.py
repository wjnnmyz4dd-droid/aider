"""Unit tests for the account snapshot telemetry endpoints.

Covers POST /account/snapshot and GET /account/status: the snapshot is stored
and returned with an age in seconds, integer position count, echoed timestamp,
and a risk-integration status field. Telemetry only — these tests also assert
the snapshot does not register a trading account (no risk/orchestrator change).

Run under an env with flask+numpy+requests available:

    python -m unittest tests.test_account_snapshot

Importing phantom_institutional writes a startup log to ~/Documents, so we
ensure that directory exists first (it exists on the target Windows VPS).
"""

import os
os.makedirs(os.path.join(os.path.expanduser("~"), "Documents"), exist_ok=True)

import unittest

import phantom_institutional as P


class TestAccountSnapshot(unittest.TestCase):
    def setUp(self):
        self.c = P.app.test_client()
        # reset the shared snapshot so tests are order-independent
        with P._account_snapshot_lock:
            P._account_snapshot.update({
                "balance": None, "equity": None, "margin": None,
                "free_margin": None, "positions_open": None,
                "timestamp": None, "received_at": None,
            })

    def test_status_empty_before_any_snapshot(self):
        r = self.c.get("/account/status")
        self.assertEqual(r.status_code, 200)
        j = r.get_json()
        self.assertFalse(j["has_snapshot"])
        self.assertIsNone(j["age_seconds"])
        self.assertIsNone(j["balance"])

    def test_snapshot_then_status_roundtrip(self):
        r = self.c.post("/account/snapshot", json={
            "balance": 100000, "equity": 99250.5, "margin": 1200,
            "free_margin": 98050.5, "positions_open": 3,
            "timestamp": "2026-07-02T12:00:00Z",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")

        j = self.c.get("/account/status").get_json()
        self.assertTrue(j["has_snapshot"])
        self.assertEqual(j["balance"], 100000.0)
        self.assertEqual(j["equity"], 99250.5)
        self.assertEqual(j["margin"], 1200.0)
        self.assertEqual(j["free_margin"], 98050.5)
        self.assertEqual(j["positions_open"], 3)          # coerced to int
        self.assertIsInstance(j["positions_open"], int)
        self.assertEqual(j["timestamp"], "2026-07-02T12:00:00Z")
        self.assertIsInstance(j["age_seconds"], (int, float))
        self.assertGreaterEqual(j["age_seconds"], 0.0)
        # integration status is one of the reported vocab values
        self.assertIn(j["risk_integration"], ("telemetry_only", "absent"))
        self.assertIn(j["risk_engine"], ("present", "absent"))

    def test_missing_fields_are_null_not_estimated(self):
        r = self.c.post("/account/snapshot", json={"equity": 5000})
        self.assertEqual(r.status_code, 200)
        j = self.c.get("/account/status").get_json()
        self.assertEqual(j["equity"], 5000.0)
        for k in ("balance", "margin", "free_margin", "positions_open", "timestamp"):
            self.assertIsNone(j[k], f"{k} should be null")

    def test_snapshot_does_not_register_trading_account(self):
        before = self.c.get("/accounts/status").get_json().get("total_accounts", 0)
        self.c.post("/account/snapshot", json={"balance": 100000, "equity": 99000})
        after = self.c.get("/accounts/status").get_json().get("total_accounts", 0)
        self.assertEqual(before, after)  # telemetry only, no orchestrator mutation


if __name__ == "__main__":
    unittest.main()

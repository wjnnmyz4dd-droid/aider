"""Tests for verify_transport_configuration.py (Part 2 of the corrective
patch): proves each evidence-gathering function reads real files
honestly (never guessing), and that the MATCHED/MISMATCH/
FALLBACK_OCCURRED/INSUFFICIENT_EVIDENCE verdict follows deterministically
from that evidence.

Like diagnose_communication.py's own test suite, the MT5-terminal-
resolution step degrades to an honest "none/ambiguous" result on this
Linux sandbox (no real MT5 install) -- `gather_evidence()`'s EA-log-
dependent fields are therefore exercised at the parsing-function level
directly, with real temp files, rather than through the full
`mt5_terminal.build_resolution_report()` path."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ._fixtures import DEPLOYMENT_DIR, write_config  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import verify_transport_configuration as vtc


class TestFindEaOnInitTransport(unittest.TestCase):
    def test_finds_transport_from_a_real_oninit_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text(
                "2026.07.21 03:30:00.000  Titan (EURUSD,M15)  TitanProtocolEA initialized. "
                "Symbol=EURUSD Magic=20260710 Transport=TRANSPORT_HTTP\n",
                encoding="utf-8",
            )
            result = vtc._find_ea_oninit_transport([log_path])
        self.assertIsNotNone(result)
        transport, line = result
        self.assertEqual(transport, "TRANSPORT_HTTP")
        self.assertIn("Transport=TRANSPORT_HTTP", line)

    def test_returns_none_when_no_oninit_line_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text("some unrelated Journal line\n", encoding="utf-8")
            result = vtc._find_ea_oninit_transport([log_path])
        self.assertIsNone(result)

    def test_keeps_the_most_recent_init_when_several_are_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text(
                "TitanProtocolEA initialized. Symbol=EURUSD Magic=20260710 Transport=TRANSPORT_SOCKET\n"
                "TitanProtocolEA initialized. Symbol=EURUSD Magic=20260710 Transport=TRANSPORT_HTTP\n",
                encoding="utf-8",
            )
            result = vtc._find_ea_oninit_transport([log_path])
        self.assertEqual(result[0], "TRANSPORT_HTTP")


class TestFindFallbackEvent(unittest.TestCase):
    def test_detects_the_real_fallback_print_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text(
                "TitanProtocolEA: Socket transport failed 5 consecutive connection attempts -- "
                "automatically falling back to HTTP transport for the remainder of this run "
                "(ADR-034 Amendment 3). To restore Socket transport...\n",
                encoding="utf-8",
            )
            result = vtc._find_fallback_event([log_path])
        self.assertIsNotNone(result)
        occurred, line = result
        self.assertTrue(occurred)
        self.assertIn("falling back to HTTP", line)

    def test_no_fallback_line_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "20260721.log"
            log_path.write_text("TitanProtocolEA: socket connected to 127.0.0.1:8788\n", encoding="utf-8")
            result = vtc._find_fallback_event([log_path])
        self.assertIsNone(result)


class TestFindBridgeListenerLines(unittest.TestCase):
    def test_finds_primary_listener_and_http_fallback_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "titan_protocol_20260721.log"
            log_path.write_text(
                "2026-07-21 03:30:00,000 INFO titan_protocol.deploy: Bridge socket service listening on 127.0.0.1:8788\n"
                "2026-07-21 03:30:00,050 INFO titan_protocol.deploy: Bridge HTTP fallback listener also active on 127.0.0.1:8787\n",
                encoding="utf-8",
            )
            listener_line, fallback_line = vtc._find_bridge_listener_lines(log_path)
        self.assertIn("Bridge socket service listening on 127.0.0.1:8788", listener_line)
        self.assertIn("Bridge HTTP fallback listener also active on 127.0.0.1:8787", fallback_line)

    def test_finds_http_fallback_bind_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "titan_protocol_20260721.log"
            log_path.write_text(
                "2026-07-21 03:30:00,000 INFO titan_protocol.deploy: Bridge socket service listening on 127.0.0.1:8788\n"
                "2026-07-21 03:30:00,050 WARNING titan_protocol.deploy: Bridge HTTP fallback listener failed to bind "
                "127.0.0.1:8787 -- [Errno 98] Address already in use (socket transport still active...)\n",
                encoding="utf-8",
            )
            _listener_line, fallback_line = vtc._find_bridge_listener_lines(log_path)
        self.assertIn("failed to bind", fallback_line)

    def test_none_log_returns_none_none(self):
        self.assertEqual(vtc._find_bridge_listener_lines(None), (None, None))


class TestVerdict(unittest.TestCase):
    def _evidence(self, **overrides):
        e = vtc.Evidence()
        for key, value in overrides.items():
            setattr(e, key, value)
        return e

    def test_matched_when_both_sides_agree_and_no_fallback(self):
        evidence = self._evidence(
            bridge_configured_transport="http", ea_configured_transport="TRANSPORT_HTTP",
            observed_transport_tally={"HTTP": 10},
        )
        self.assertEqual(vtc._verdict(evidence), "MATCHED")

    def test_mismatch_when_configured_sides_disagree(self):
        evidence = self._evidence(bridge_configured_transport="http", ea_configured_transport="TRANSPORT_SOCKET")
        self.assertEqual(vtc._verdict(evidence), "MISMATCH")

    def test_fallback_occurred_takes_priority_over_configured_agreement(self):
        evidence = self._evidence(
            bridge_configured_transport="socket", ea_configured_transport="TRANSPORT_SOCKET",
            fallback_occurred=True,
        )
        self.assertEqual(vtc._verdict(evidence), "FALLBACK_OCCURRED")

    def test_mismatch_when_observed_traffic_disagrees_with_configured_value(self):
        """Configured values agree, but the EA is actually observed
        sending requests over a different transport than either side
        claims to be configured for -- must not be reported as MATCHED."""
        evidence = self._evidence(
            bridge_configured_transport="http", ea_configured_transport="TRANSPORT_HTTP",
            observed_transport_tally={"Socket": 3},
        )
        self.assertEqual(vtc._verdict(evidence), "MISMATCH")

    def test_insufficient_evidence_when_ea_configured_transport_unknown(self):
        evidence = self._evidence(bridge_configured_transport="http", ea_configured_transport=None)
        self.assertEqual(vtc._verdict(evidence), "INSUFFICIENT_EVIDENCE")


class TestGatherEvidenceBridgeSide(unittest.TestCase):
    """The EA-side fields depend on mt5_terminal.build_resolution_report(),
    which honestly reports "no unambiguous instance" on this Linux
    sandbox (same convention as every other MT5-detection code in this
    repository, per diagnose_communication.py's own test suite) -- this
    exercises the Bridge-config side of gather_evidence(), which does not
    depend on a real MT5 install."""

    def test_bridge_configured_transport_is_read_from_the_real_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), overrides={"transport": "socket"})
            evidence = vtc.gather_evidence(config_path, ["20260721"])
        self.assertEqual(evidence.bridge_configured_transport, "socket")
        self.assertIsNone(evidence.ea_configured_transport)
        self.assertTrue(any("Cannot resolve exactly one running MT5 instance" in note for note in evidence.notes))


if __name__ == "__main__":
    unittest.main()

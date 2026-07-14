"""Protocol/structural tests for TitanProtocolEA.mq5's server-side
emergency-stop synchronization (Final Release Hardening, requirement 3).

MQL5 cannot be compiled or executed outside MetaEditor/a real MT5
terminal, so these are source-inspection tests -- the same technique
this repo's `test_structural_boundary.py` suite already uses for
architecture boundaries. They verify the *contract* is wired
correctly in the source (the poll response field is read, the local
input is preserved, positions are never auto-closed, transitions are
logged); they do not and cannot substitute for the real
MetaEditor-compile + demo-attach verification tracked separately as
PENDING REAL MT5 (see the release hardening report / KNOWN_GAPS.md)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EA_PATH = REPO_ROOT / "mt5" / "TitanProtocolEA.mq5"
BRIDGE_SERVER_PATH = REPO_ROOT / "titan_protocol" / "bridge" / "server.py"


class _EASourceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8")


class TestServerFlagIsReadFromTheExistingPollEndpoint(_EASourceTestCase):
    def test_no_new_endpoint_is_introduced(self):
        """The mission's own constraint: reuse the existing poll
        response field, never add a second endpoint/poll for it."""
        http_get_call_count = len(re.findall(r"HttpGet\([^)]*\"/bridge/commands/poll", self.source))
        self.assertEqual(http_get_call_count, 1, "expected exactly one HttpGet() call site for /bridge/commands/poll")

    def test_emergency_stop_field_is_parsed_from_the_poll_response(self):
        self.assertIn('JsonGetBool(response, "emergency_stop"', self.source)

    def test_a_json_bool_parser_exists(self):
        self.assertIn("bool JsonGetBool(", self.source)


class TestEffectiveStoppedStateIsLocalOrServer(_EASourceTestCase):
    def test_is_emergency_stopped_ors_local_and_server_flags(self):
        match = re.search(r"bool IsEmergencyStopped\(\)\s*\{[^}]*\}", self.source, re.DOTALL)
        self.assertIsNotNone(match, "IsEmergencyStopped() helper not found")
        body = match.group(0)
        self.assertIn("EmergencyDisable", body)
        self.assertIn("g_serverEmergencyStop", body)
        self.assertIn("||", body)

    def test_local_emergency_disable_input_is_unchanged_and_independent(self):
        """The local kill switch must remain its own, still-fully-halting
        input -- OnTimer's own top-level `if(EmergencyDisable) return;`
        early-exit must still exist unmodified."""
        self.assertIn("input bool   EmergencyDisable", self.source)
        self.assertIn("if(EmergencyDisable)\n      return;", self.source)


class TestExecutionCommandsAreRejectedWhileStopped(_EASourceTestCase):
    def test_poll_and_execute_commands_checks_effective_stopped_state_before_dispatch(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{.*", self.source, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(0)
        stop_check_pos = body.find("IsEmergencyStopped()")
        buy_dispatch_pos = body.find('kind == "BUY"')
        self.assertGreater(stop_check_pos, 0, "IsEmergencyStopped() is not checked in PollAndExecuteCommands")
        self.assertGreater(buy_dispatch_pos, 0)
        self.assertLess(stop_check_pos, buy_dispatch_pos, "emergency-stop check must run before command dispatch")

    def test_rejected_commands_are_reported_not_silently_dropped(self):
        self.assertIn('ReportError("EMERGENCY_STOP_ACTIVE"', self.source)


class TestActivationAndClearanceAreLogged(_EASourceTestCase):
    def test_activation_is_logged(self):
        self.assertIn("emergency stop ACTIVATED", self.source)

    def test_clearance_is_logged(self):
        self.assertIn("emergency stop CLEARED", self.source)

    def test_logging_is_edge_triggered_not_every_cycle(self):
        """Must compare against the previous value before printing --
        otherwise every single poll cycle would log, spamming the
        terminal log while a stop is held active/inactive."""
        match = re.search(r"if\(newServerEmergencyStop != g_serverEmergencyStop\)", self.source)
        self.assertIsNotNone(match, "transition logging must be gated on an actual state change")


class TestExistingPositionsAreNeverAutoClosed(_EASourceTestCase):
    def test_no_position_close_call_appears_near_the_emergency_stop_handling(self):
        """Mission's own hard constraint: do not automatically close
        existing positions on an emergency stop. Confirms no
        PositionClose/PositionClosePartial call was added inside
        PollAndExecuteCommands's emergency-stop branch."""
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{.*?\n  \}", self.source, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(0)
        emergency_branch_start = body.find("IsEmergencyStopped()")
        emergency_branch_end = body.find("continue;", emergency_branch_start) + len("continue;")
        branch_text = body[emergency_branch_start:emergency_branch_end]
        self.assertNotIn("PositionClose", branch_text)
        self.assertNotIn("g_trade.PositionClose", branch_text)


class TestServerSidePollResponseAlreadyExposesTheField(unittest.TestCase):
    """Confirms the Python-side half of the contract this EA change
    depends on -- `/bridge/commands/poll` already returns
    `emergency_stop` in its JSON body (pre-existing, unmodified by this
    phase; see `titan_protocol/bridge/server.py`)."""

    def test_poll_handler_returns_emergency_stop_field(self):
        text = BRIDGE_SERVER_PATH.read_text(encoding="utf-8")
        match = re.search(r"def _handle_poll_commands\(.*?\n(?:.*\n)*?    return 200, \{[^}]*\}", text)
        self.assertIsNotNone(match, "_handle_poll_commands not found in expected shape")
        self.assertIn('"emergency_stop"', match.group(0))


if __name__ == "__main__":
    unittest.main()

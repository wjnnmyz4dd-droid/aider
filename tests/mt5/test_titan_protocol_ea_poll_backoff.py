"""Source-inspection tests for ADR-034 Amendment 5 (HTTP poll-level
exponential backoff around PollAndExecuteCommands()).

Root cause: /bridge/commands/poll was retried at full intensity every
OnTimer tick (once per second) forever, with no cooldown between
failures. This mirrors that same base*2^attempt, capped backoff pattern
for command polling. Since ADR-034 Amendment 10 removed native socket
transport entirely, HTTP is the only transport and this cooldown
unconditionally gates every poll.

MQL5 cannot be compiled or executed outside MetaEditor/a real MT5
terminal, so these are source-inspection tests, the same technique
`test_titan_protocol_ea_transport_classification.py` already uses for
this file."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EA_PATH = REPO_ROOT / "mt5" / "TitanProtocolEA.mq5"


class _EASourceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8")


class TestPollBackoffInputsExist(_EASourceTestCase):
    def test_base_and_max_delay_inputs_declared_with_required_defaults(self):
        self.assertIn("input int    PollBackoffBaseDelayMs   = 500;", self.source)
        self.assertIn("input int    PollBackoffMaxDelayMs    = 15000;", self.source)


class TestPollCooldownGate(_EASourceTestCase):
    def test_cooldown_helper_exists(self):
        self.assertIn("bool IsPollCooldownElapsed()", self.source)

    def test_poll_and_execute_commands_is_gated_by_cooldown(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        self.assertIsNotNone(match, "PollAndExecuteCommands() not found")
        body = match.group(1)
        self.assertIn("IsPollCooldownElapsed()", body)

    def test_cooldown_gate_is_unconditional(self):
        """HTTP is the only transport since ADR-034 Amendment 10 -- the
        cooldown gate no longer needs (or has) a transport conditional."""
        match = re.search(
            r"if\(!IsPollCooldownElapsed\(\)\)",
            self.source,
        )
        self.assertIsNotNone(match)

    def test_cooldown_check_precedes_the_actual_poll_call(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        body = match.group(1)
        cooldown_pos = body.index("IsPollCooldownElapsed()")
        poll_pos = body.index("BridgePollCommands(status)")
        self.assertLess(cooldown_pos, poll_pos, "cooldown check must gate the poll call, not follow it")


class TestPollBackoffStateTransitions(_EASourceTestCase):
    def test_failure_increments_counter(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        body = match.group(1)
        failure_branch = re.search(r'if\(response == ""\)\s*\{(.*?)return; // no successful contact', body, re.DOTALL)
        self.assertIsNotNone(failure_branch, "empty-response failure branch not found")
        failure_body = failure_branch.group(1)
        self.assertIn("g_consecutivePollFailures++", failure_body)

    def test_success_resets_failure_counter_and_records_last_success(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        body = match.group(1)
        self.assertIn("g_consecutivePollFailures = 0;", body)
        self.assertIn("g_lastSuccessfulPollAt = TimeCurrent();", body)

    def test_exponential_backoff_formula_matches_spec(self):
        """base * 2^attempt, capped -- used once in IsPollCooldownElapsed()
        and once in PollAndExecuteCommands()'s own failure branch."""
        matches = re.findall(
            r"MathMin\(\(double\)PollBackoffBaseDelayMs \* MathPow\(2\.0, cappedAttempt\),\s*"
            r"\(double\)PollBackoffMaxDelayMs\)",
            self.source,
        )
        self.assertEqual(
            len(matches), 2,
            "expected the base*2^attempt/capped formula once in IsPollCooldownElapsed() and once in the failure branch",
        )


class TestPollFailureLoggedOnceNotEveryTick(_EASourceTestCase):
    def test_entering_cooldown_is_logged_with_required_diagnostic_fields(self):
        self.assertIn("entering HTTP poll cooldown", self.source)
        match = re.search(r'Print\("TitanProtocolEA: /bridge/commands/poll failed.*?\);', self.source, re.DOTALL)
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertIn("consecutivePollFailures=", body)
        self.assertIn("cooldownMs=", body)
        self.assertIn("nextPollAt=", body)
        self.assertIn("lastSuccessfulPollAt=", body)

    def test_skipped_ticks_during_cooldown_produce_no_log_line_at_all(self):
        """The cooldown-gated early return in PollAndExecuteCommands()
        must be a bare `return;` -- no Print() call on that path, since
        that is what actually eliminates the per-tick Experts-log spam
        (skipped ticks never even reach BridgePollCommands()'s own
        TITAN_DIAG ATTEMPT line)."""
        match = re.search(
            r"if\(!IsPollCooldownElapsed\(\)\)\n\s*(return;[^\n]*)\n",
            self.source,
        )
        self.assertIsNotNone(match)
        self.assertTrue(match.group(1).strip().startswith("return;"))


if __name__ == "__main__":
    unittest.main()

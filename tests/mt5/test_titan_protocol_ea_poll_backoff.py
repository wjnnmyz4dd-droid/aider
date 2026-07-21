"""Source-inspection tests for ADR-034 Amendment 5 (HTTP poll-level
exponential backoff around PollAndExecuteCommands()).

Root cause: /bridge/commands/poll was retried at full intensity every
OnTimer tick (once per second) forever, with no cooldown between
failures -- unlike EnsureSocketConnected()'s own reconnect backoff. A
persistently failing poll therefore produced continuous per-second
Experts-log spam ("looping"). This mirrors that same base*2^attempt,
capped backoff pattern for command polling, HTTP-only -- Socket
transport is untouched (its own reconnect backoff already governs its
retry pacing).

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

    def test_cooldown_gate_only_applies_to_http_not_socket(self):
        """Explicit constraint: must not change Socket behavior at all --
        the gate is conditioned on g_effectiveTransport == TRANSPORT_HTTP."""
        match = re.search(
            r"if\(g_effectiveTransport == TRANSPORT_HTTP && !IsPollCooldownElapsed\(\)\)",
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
    def test_failure_increments_counter_and_is_http_only(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        body = match.group(1)
        failure_branch = re.search(r'if\(response == ""\)\s*\{(.*?)return; // no successful contact', body, re.DOTALL)
        self.assertIsNotNone(failure_branch, "empty-response failure branch not found")
        failure_body = failure_branch.group(1)
        self.assertIn("g_effectiveTransport == TRANSPORT_HTTP", failure_body)
        self.assertIn("g_consecutivePollFailures++", failure_body)

    def test_success_resets_failure_counter_and_records_last_success(self):
        match = re.search(r"void PollAndExecuteCommands\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        body = match.group(1)
        self.assertIn("g_consecutivePollFailures = 0;", body)
        self.assertIn("g_lastSuccessfulPollAt = TimeCurrent();", body)

    def test_exponential_backoff_formula_matches_spec(self):
        """base * 2^attempt, capped -- same technique EnsureSocketConnected()
        already uses for its own reconnect backoff."""
        self.assertEqual(
            self.source.count(
                "MathMin((double)PollBackoffBaseDelayMs * MathPow(2.0, cappedAttempt),\n"
                "                               (double)PollBackoffMaxDelayMs)"
            )
            + self.source.count(
                "MathMin((double)PollBackoffBaseDelayMs * MathPow(2.0, cappedAttempt),\n"
                "                                     (double)PollBackoffMaxDelayMs)"
            ),
            2,
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
            r"if\(g_effectiveTransport == TRANSPORT_HTTP && !IsPollCooldownElapsed\(\)\)\n\s*(return;[^\n]*)\n",
            self.source,
        )
        self.assertIsNotNone(match)
        self.assertTrue(match.group(1).strip().startswith("return;"))


class TestSocketBehaviorUnchanged(_EASourceTestCase):
    def test_ensure_socket_connected_body_has_no_poll_backoff_coupling(self):
        """Explicit constraint: do not modify socket behavior.
        EnsureSocketConnected()'s own reconnect-backoff logic must have
        no reference to any of the new HTTP poll-cooldown state -- the
        two backoff mechanisms are deliberately independent."""
        match = re.search(r"bool EnsureSocketConnected\(\)\s*\{(.*?)\n  \}", self.source, re.DOTALL)
        self.assertIsNotNone(match, "EnsureSocketConnected() not found")
        body = match.group(1)
        self.assertNotIn("g_consecutivePollFailures", body)
        self.assertNotIn("g_lastPollAttemptAt", body)
        self.assertNotIn("PollBackoffBaseDelayMs", body)
        self.assertNotIn("PollBackoffMaxDelayMs", body)


if __name__ == "__main__":
    unittest.main()

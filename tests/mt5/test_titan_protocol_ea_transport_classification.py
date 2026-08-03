"""Source-inspection tests for mt5/TitanProtocolEA.mq5's HTTP-status
classification (Runtime Audit Phase 4 / ADR-034 Amendment 4), which
remains after Amendment 10 removed native socket transport entirely and
made HTTP the sole transport:

`HttpPost()`/`HttpGet()` classify `WebRequest()`'s return value with a
strict 100-599 HTTP-status boundary, so a WinINet transport pseudo-
status (e.g. 1001) is never printed as "rejected, HTTP <n>" or treated
as a genuine Bridge response.

MQL5 cannot be compiled or executed outside MetaEditor/a real MT5
terminal, so these are source-inspection tests -- the same technique
`test_structural_boundary.py` and `test_titan_protocol_ea_emergency_stop.py`
already use for this file. They verify the contract is wired correctly
in the source; they do not substitute for a real MetaEditor-compile +
demo-attach verification."""

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


class TestNoSocketTransportRemains(_EASourceTestCase):
    """ADR-034 Amendment 10 -- native socket transport was removed
    entirely; guards against any of it silently reappearing."""

    def test_no_transport_enum_or_input(self):
        self.assertNotIn("ENUM_TRANSPORT_MODE", self.source)
        self.assertNotIn("TRANSPORT_SOCKET", self.source)
        self.assertNotIn("TRANSPORT_HTTP", self.source)

    def test_no_socket_functions_or_globals(self):
        self.assertNotIn("SocketConnect", self.source)
        self.assertNotIn("SocketCreate", self.source)
        self.assertNotIn("g_effectiveTransport", self.source)
        self.assertNotIn("g_hasFallenBackToHttp", self.source)


class TestHttpStatusClassificationBoundary(_EASourceTestCase):
    def test_shared_boundary_helper_exists_with_the_right_range(self):
        match = re.search(r"bool IsValidHttpStatus\(int status\)\s*\{[^}]*\}", self.source, re.DOTALL)
        self.assertIsNotNone(match, "IsValidHttpStatus() helper not found")
        body = match.group(0)
        self.assertIn("status >= 100", body)
        self.assertIn("status < 600", body)

    def test_http_post_and_get_both_use_the_shared_boundary_helper(self):
        self.assertEqual(
            self.source.count("if(IsValidHttpStatus(status))"), 2,
            "expected exactly one IsValidHttpStatus() branch each in HttpPost() and HttpGet()",
        )

    def test_neither_helper_uses_the_bare_status_greater_than_zero_check_anymore(self):
        """The original bug: `if(status > 0)` treated any positive
        WebRequest() return as a real HTTP response. Both functions must
        route through the shared boundary helper instead."""
        self.assertNotIn("if(status > 0)", self.source)

    def test_pseudo_status_failure_function_exists_and_is_called_from_both_helpers(self):
        self.assertIn("void PrintHttpTransportPseudoStatusFailure(", self.source)
        self.assertEqual(
            self.source.count('PrintHttpTransportPseudoStatusFailure("POST", endpoint, status, lastErr, elapsedMs);'), 1,
        )
        self.assertEqual(
            self.source.count('PrintHttpTransportPseudoStatusFailure("GET", endpoint, status, lastErr, elapsedMs);'), 1,
        )

    def test_pseudo_status_path_emits_no_response_marker_not_blocked(self):
        match = re.search(
            r"void PrintHttpTransportPseudoStatusFailure\([^)]*\)\s*\{.*?\n  \}", self.source, re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertIn("TITAN_DIAG NO_RESPONSE transport=HTTP", body)
        self.assertNotIn("TITAN_DIAG BLOCKED", body)

    def test_pseudo_status_path_never_uses_forbidden_wording(self):
        match = re.search(
            r"void PrintHttpTransportPseudoStatusFailure\([^)]*\)\s*\{.*?\n  \}", self.source, re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertNotIn("HTTP \", webRequestReturn", body)
        self.assertNotIn("rejected", body)
        self.assertNotIn("Bridge rejected", body)

    def test_pseudo_status_path_includes_return_value_lasterror_and_elapsed(self):
        match = re.search(
            r"void PrintHttpTransportPseudoStatusFailure\([^)]*\)\s*\{.*?\n  \}", self.source, re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(0)
        self.assertIn("webRequestReturn", body)
        self.assertIn("lastErr", body)
        self.assertIn("elapsedMs", body)

    def test_genuine_rejection_wording_only_appears_guarded_by_the_boundary_helper(self):
        """"rejected, HTTP <n>" must only ever be reachable once the
        boundary helper has already confirmed a genuine in-range status
        -- exactly one occurrence in HttpPost, one in HttpGet."""
        self.assertEqual(self.source.count('rejected, HTTP ", status'), 2)

    def test_diagnostic_elapsed_measurement_is_no_longer_gated_by_diagnostic_mode(self):
        """elapsedMs must be available for the pseudo-status marker
        regardless of DiagnosticMode -- startTick can no longer be
        conditionally zeroed."""
        self.assertNotIn("uint startTick = DiagnosticMode ? GetTickCount() : 0;", self.source)
        self.assertEqual(self.source.count("uint startTick = GetTickCount();"), 2)


if __name__ == "__main__":
    unittest.main()

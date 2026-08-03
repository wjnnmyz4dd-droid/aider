"""Tests for diagnose_wininet.py -- the WinINet-layer proxy/WPAD
diagnostic for the `pseudoStatus=1001`/`GetLastError=5203` `WebRequest()`
failure signature documented as still-open in `KNOWN_GAPS.md` section 11.

`read_proxy_registry()`'s Windows-only path (winreg) cannot be exercised
on this Linux sandbox -- exactly like every other MT5-instance-detection
code in this repository, it degrades to an honest "Not running on
Windows" result instead of fabricating registry state (asserted below).
The platform-independent logic (`_bypasses_loopback`, `_timed_request`,
`run_timing_comparison`) is exercised directly, including one real,
end-to-end timed HTTP round trip against the actual Bridge server code
(server.py), not a mocked clock or fabricated timing value.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout

from ._fixtures import DEPLOYMENT_DIR  # noqa: F401 -- ensures deployment_windows/ is on sys.path

import diagnose_wininet as dw

from tests.titan_protocol.bridge.test_http_server import HttpServerTestCase


class TestBypassesLoopback(unittest.TestCase):
    def test_empty_string_does_not_bypass(self):
        self.assertFalse(dw._bypasses_loopback(""))

    def test_local_token_bypasses(self):
        self.assertTrue(dw._bypasses_loopback("*.example.com;<local>"))

    def test_explicit_loopback_ip_bypasses(self):
        self.assertTrue(dw._bypasses_loopback("127.0.0.1"))

    def test_loopback_ip_with_port_wildcard_bypasses(self):
        self.assertTrue(dw._bypasses_loopback("127.0.0.1:*"))

    def test_unrelated_override_does_not_bypass(self):
        self.assertFalse(dw._bypasses_loopback("*.example.com;10.0.0.1"))

    def test_case_insensitive_local_token(self):
        self.assertTrue(dw._bypasses_loopback("<LOCAL>"))


class TestReadProxyRegistryOnNonWindows(unittest.TestCase):
    def test_returns_none_and_reports_not_windows(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = dw.read_proxy_registry()
        self.assertIsNone(result)
        self.assertIn("Not running on Windows", buf.getvalue())


class TestTimedRequestAndTimingComparison(HttpServerTestCase):
    """Real end-to-end timing against the actual Bridge HTTP server --
    status/rejection reason is irrelevant to this diagnostic (per its own
    docstring), only that a real elapsed time is measured for both the
    system-proxy-aware and proxy-bypassed code paths."""

    def _bridge_url(self, path: str) -> str:
        host, port = self.server.server_address[0], self.server.server_address[1]
        return f"http://{host}:{port}{path}"

    def test_timed_request_direct_bypass_returns_real_elapsed_and_outcome(self):
        elapsed, outcome = dw._timed_request(self._bridge_url("/bridge/heartbeat"), use_system_proxy=False)
        self.assertIsInstance(elapsed, float)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertTrue(outcome.startswith("HTTP") or ":" in outcome)

    def test_timed_request_system_proxy_path_also_returns_real_elapsed(self):
        """No proxy is actually configured in this sandbox, so
        getproxies() is empty and this should behave the same as the
        bypass path -- the point is only that the code path executes and
        produces a real measurement, not a fabricated one."""
        elapsed, outcome = dw._timed_request(self._bridge_url("/bridge/heartbeat"), use_system_proxy=True)
        self.assertIsInstance(elapsed, float)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertTrue(outcome.startswith("HTTP") or ":" in outcome)

    def test_run_timing_comparison_against_real_bridge_reports_both_timings(self):
        host, port = self.server.server_address[0], self.server.server_address[1]
        buf = io.StringIO()
        with redirect_stdout(buf):
            clean = dw.run_timing_comparison(host, port)
        output = buf.getvalue()
        self.assertIn("With system proxy settings honored", output)
        self.assertIn("With proxy explicitly bypassed", output)
        self.assertIsInstance(clean, bool)

    def test_run_timing_comparison_unreachable_host_still_completes(self):
        """An unreachable target (e.g. Bridge not running) must still
        produce two real timed outcomes rather than raising -- the
        diagnostic's whole point is to work even when the Bridge is
        down/unreachable."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            dw.run_timing_comparison("127.0.0.1", 1)  # port 1: reliably refused
        output = buf.getvalue()
        self.assertIn("With system proxy settings honored", output)
        self.assertIn("With proxy explicitly bypassed", output)


if __name__ == "__main__":
    unittest.main()

"""EA liveness — the ONE owner of "is the Session Edge EA alive and polling THIS
bridge?" (distinct from H5 instruction/ACK health in producer/bridge_health.py).

It reads a recurring, EA-written heartbeat (``<bridge_root>/health/ea_status.json``)
and proves — from an EA-originated artifact, never fabricated by Python — that an EA is
currently running, polling, and bound to the SAME bridge folder Python selected. It has
ZERO trade authority: it reads one file, places/claims nothing, and its result only
gates OBSERVATIONAL readiness. Python must never create this file (a test asserts it).

Heartbeat contract (written by the EA timer loop; see ea_mt5/SessionEdgeExecutionEA.mq5):
  { "artifact":"session_edge_ea_status", "schema_version":1, "ea_id":..., "timestamp":ISO,
    "bridge_root":"session_edge_bridge", "use_common_folder":false, "poll_seconds":5,
    "data_path":"<terminal data path>", "account_login":<int>, "polling_active":true }
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from . import mt5_terminal

EA_STATUS_ARTIFACT = "session_edge_ea_status"
EA_STATUS_SCHEMA = 1
EA_STATUS_FILE = "ea_status.json"

# Freshness derived from the EA's own poll cadence (never a huge arbitrary timeout):
#   freshness_limit = max(MIN_FRESH_FLOOR_SEC, poll_seconds * FRESH_MULT)
# A healthy EA rewrites the heartbeat every PollSeconds; the floor tolerates scheduler
# jitter / a couple of missed ticks. Default poll (5s) -> max(15, 20) = 20s.
MIN_FRESH_FLOOR_SEC = 15.0
FRESH_MULT = 4.0

# States (only PASS is EA_LIVENESS_PASS).
PASS = "PASS"
MISSING = "MISSING"
STALE = "STALE"
MALFORMED = "MALFORMED"
WRONG_BRIDGE = "WRONG_BRIDGE"
UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"


class Liveness:
    def __init__(self, state, detail="", data=None):
        self.state, self.detail, self.data = state, detail, (data or {})

    @property
    def ok(self):
        return self.state == PASS


def freshness_limit(poll_seconds):
    try:
        p = float(poll_seconds)
    except (TypeError, ValueError):
        p = 0.0
    if p <= 0:
        p = 5.0
    return max(MIN_FRESH_FLOOR_SEC, p * FRESH_MULT)


def status_path(bridge_root):
    return Path(bridge_root) / "health" / EA_STATUS_FILE


def _ea_implied_bridge(data_path, bridge_root_name, use_common):
    """The absolute bridge the EA's own report implies (terminal Files, non-common)."""
    if not data_path:
        return None
    if use_common:
        return None                     # common-folder path not derivable from data_path
    return str(Path(data_path) / "MQL5" / "Files" / bridge_root_name)


def read_ea_status(bridge_root, now, *, expected_bridge_root_name="session_edge_bridge",
                   expected_use_common=False, expected_bridge_abspath=None):
    """Validate the EA heartbeat for ``bridge_root`` at instant ``now`` (injected).
    Returns a Liveness whose ``ok`` is True ONLY for a fresh, same-bridge, well-formed,
    known-schema heartbeat. Never raises; never writes."""
    p = status_path(bridge_root)
    try:
        text = p.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return Liveness(MISSING, f"no {EA_STATUS_FILE} at {p} — EA not writing to this bridge")
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        return Liveness(MALFORMED, f"unparseable {EA_STATUS_FILE}")
    if obj.get("artifact") != EA_STATUS_ARTIFACT or obj.get("schema_version") != EA_STATUS_SCHEMA:
        return Liveness(UNKNOWN_SCHEMA,
                        f"artifact/schema mismatch ({obj.get('artifact')!r}/{obj.get('schema_version')!r})")
    ts = serialize.parse_iso(obj.get("timestamp"))
    if ts is None:
        return Liveness(MALFORMED, "missing/invalid timestamp")
    # same-bridge: name + common-folder mode must match what Python selected...
    if str(obj.get("bridge_root")) != str(expected_bridge_root_name):
        return Liveness(WRONG_BRIDGE,
                        f"heartbeat BridgeRoot {obj.get('bridge_root')!r} != {expected_bridge_root_name!r}")
    if bool(obj.get("use_common_folder")) != bool(expected_use_common):
        return Liveness(WRONG_BRIDGE,
                        f"UseCommonFolder {bool(obj.get('use_common_folder'))} != {bool(expected_use_common)}")
    # ...and, when the EA reports its data_path AND Python knows the absolute bridge,
    # the implied absolute bridge must match (strongest proof; else ENV-limited to name).
    implied = _ea_implied_bridge(obj.get("data_path"), expected_bridge_root_name,
                                 bool(obj.get("use_common_folder")))
    if expected_bridge_abspath and implied and not mt5_terminal.paths_equal(implied, expected_bridge_abspath):
        return Liveness(WRONG_BRIDGE,
                        f"EA data_path implies {implied} != selected {expected_bridge_abspath}")
    if not obj.get("polling_active"):
        return Liveness(STALE, "heartbeat present but polling_active is not true")
    age = (now - ts).total_seconds()
    limit = freshness_limit(obj.get("poll_seconds"))
    if age < -limit:
        return Liveness(STALE, f"heartbeat timestamp is in the future ({age:.0f}s)")
    if age > limit:
        return Liveness(STALE, f"heartbeat age {age:.0f}s > limit {limit:.0f}s (EA stalled/stopped?)")
    return Liveness(PASS, f"fresh EA heartbeat ({age:.0f}s ≤ {limit:.0f}s)", data=obj)

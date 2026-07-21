"""Deterministic Bridge<->MT5 communication root-cause classifier
(Runtime Audit Phase 3).

Context: ADR-034 already established (an earlier session, via exhaustive
code review and direct curl testing) that the "1003"/"1001"/"4014"
symptoms an operator sees inside MT5 are undocumented MT5-side WinINet/
socket-permission pseudo-statuses, generated inside the terminal's own
network stack -- never emitted by this Bridge. Runtime Audit Phase 2
(server.describe_rejection) then instrumented every rejection this
Bridge genuinely can produce with an exact one-line cause, on both
transports.

This script closes the remaining gap: proving, from real evidence and
never a guess, which of exactly four mutually exclusive states a given
request fell into:

  1. MT5 never attempted the request.
  2. MT5 attempted it, but it was blocked before reaching the Bridge
     (WebRequest()/SocketConnect()/SocketSend() itself failed).
  3. The Bridge received it and rejected it -- exact reason from
     server.describe_rejection().
  4. The Bridge received it and accepted it.

Evidence sources (never inferred, always read from a real file):
  - The EA's own MQL5\\Logs\\<date>.log in its resolved Data Folder --
    every Print() call in TitanProtocolEA.mq5 lands here (confirmed
    against MetaQuotes' own documentation of the terminal's file
    structure, not assumed). This module never touches MT5's platform-
    level logs\\ folder (a different, unrelated log covering the
    Journal tab, not the Experts tab Print() output lands on).
  - The Bridge's own persisted logs: bridge_console.log (server.py's
    print()-based per-request lifecycle block, one per HTTP request,
    success or failure) and the newest titan_protocol_*.log (the
    `logging` module's records, which is where socket_transport.py's
    per-request accept/reject lines land).

Matching method and its one necessary assumption, stated plainly rather
than silently relied upon: every timestamp compared here is UTC on both
sides (the EA's TimeCurrent(), per TimeToIsoString()'s own documented
convention, and the Bridge's _utc_now()) -- this only holds if the Bridge
and the MT5 terminal run on the same machine (or two clocks kept in sync),
which is this deployment's documented supported topology. Two events
(one EA-side, one Bridge-side) for the same route are matched only if
they fall within --window-seconds of each other (default 10s); ATTEMPT
lines with no match of any kind are reported honestly as unmatched
(possible additional causes: response lost after the Bridge processed it,
or the window was too narrow) rather than forced into one of the four
states.

Usage:
    python diagnose_communication.py [path/to/titan_protocol_config.json]
        [--window-seconds N] [--date YYYYMMDD] [--limit N]

Exit code: 0 if every EA attempt in the scanned window resolved to a
state-3 or state-4 classification (Bridge received it, whatever the
outcome); 1 if any request classified as state 1 or state 2, or could
not be classified at all; 2 on a configuration/environment error.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    for candidate in (here, here.parent):
        if (candidate / "titan_protocol").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Titan Protocol installation root (a folder containing "
        f"both titan_protocol/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


_REPO_ROOT = _find_repo_root(_HERE)
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_HERE))

import mt5_terminal  # noqa: E402
from config_loader import ConfigError, load_settings  # noqa: E402
# Reused, not re-derived: the single source of truth for socket route name
# <-> HTTP path already lives in socket_transport.py (ADR-034). Duplicating
# it here would risk the two silently drifting apart.
from titan_protocol.bridge.socket_transport import (  # noqa: E402
    _COMMANDS_POLL_ROUTE,
    _ROUTE_TO_HTTP_PATH,
)

# validation.py's real, confirmed check order (api_key -> magic_number ->
# symbol_allowed, short-circuiting on first failure -- see
# validate_inbound_message()) is what every mapping below is derived from;
# none of this is guessed. "unknown" means this script genuinely cannot
# tell from the rejection label alone whether that sub-check ran (e.g. an
# invalid_payload exception can occur inside a route handler either before
# or after validate_inbound_message, depending on that handler's own
# field access order) -- reported as such rather than asserted.
_YES, _NO, _NA, _UNKNOWN = "Yes", "No", "N/A (not reached)", "Unknown (cannot be derived from the rejection label alone)"

# reason -> (auth_passed, magic_number_matched, validation_passed)
_REASON_TO_SUBFIELDS = {
    None: (_YES, _YES, _YES),  # 2xx
    "API key missing": (_NO, _NA, _NA),
    "API key mismatch": (_NO, _NA, _NA),
    "MagicNumber mismatch": (_YES, _NO, _NA),
    "Unknown route": (_NA, _NA, _NA),  # route never matched -- nothing downstream ever runs
    "Malformed request body (not valid JSON)": (_NA, _NA, _NA),
    "Request body is not a JSON object": (_NA, _NA, _NA),
    "Malformed socket frame (not valid JSON)": (_NA, _NA, _NA),
    "Socket frame missing/invalid seq": (_NA, _NA, _NA),
    "Socket frame missing/invalid route": (_NA, _NA, _NA),
    "Socket frame missing/invalid body": (_NA, _NA, _NA),
    "Duplicate or replayed socket seq": (_NA, _NA, _NA),
}
# Every other named validation rejection (symbol/volume/SL/TP/timestamp/
# correlation-id/bridge-not-ready/emergency-stop/market-data-not-configured)
# implies auth and magic_number both already passed, per the same
# confirmed check order -- validate_inbound_message() runs first and
# short-circuits before any handler-specific check below it is reached.
_VALIDATION_FAILURE_REASONS = {
    "Symbol not in allowed list", "Invalid volume", "Volume exceeds max lot size",
    "Invalid stop loss", "Invalid take profit", "Timestamp in future", "Stale timestamp",
    "Missing correlation id", "Duplicate correlation id", "Unknown correlation id",
    "Bridge not ready", "Emergency stop active", "Market data ingestion not configured",
}


def _subfields_for_reason(reason: Optional[str]):
    if reason in _REASON_TO_SUBFIELDS:
        return _REASON_TO_SUBFIELDS[reason]
    if reason in _VALIDATION_FAILURE_REASONS:
        return (_YES, _YES, _NO)
    if reason is not None and reason.startswith("Invalid payload -- "):
        return (_UNKNOWN, _UNKNOWN, _UNKNOWN)
    return (_UNKNOWN, _UNKNOWN, _UNKNOWN)  # an as-yet-unseen label -- do not guess


@dataclass
class EaEvent:
    kind: str  # ATTEMPT | BLOCKED | NO_RESPONSE
    route: str
    transport: str  # HTTP | Socket
    timestamp: datetime
    detail: str
    source_file: str
    source_line: str


@dataclass
class BridgeEvent:
    timestamp: datetime
    transport: str  # HTTP | Socket
    route: str  # HTTP path (e.g. "/bridge/heartbeat") for HTTP; short route name for Socket
    rejection_reason: Optional[str]
    response_status: Optional[int]
    source_file: str
    source_line: str


_EA_TAG_RE = re.compile(r"TITAN_DIAG\s+(ATTEMPT|BLOCKED|NO_RESPONSE)\s+(.*)$")
_KV_RE = re.compile(r"(\w+)=(\S+)")


def _parse_ea_log(path: Path) -> List[EaEvent]:
    """Deliberately ignores whatever timestamp/context prefix MT5 itself
    puts on each Experts-log line (its exact column format is not
    something this script asserts, to avoid guessing at an undocumented
    detail) -- the only timestamp trusted here is the one this EA prints
    itself (time=<ISO8601>, from TimeToIsoString(TimeCurrent()))."""
    events: List[EaEvent] = []
    try:
        text = path.read_text(encoding="utf-16", errors="strict")
    except (UnicodeError, OSError):
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeError, OSError):
            text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        match = _EA_TAG_RE.search(line)
        if not match:
            continue
        kind, fields_text = match.group(1), match.group(2)
        fields = dict(_KV_RE.findall(fields_text))
        time_value = fields.get("time")
        if time_value is None:
            continue
        try:
            timestamp = datetime.fromisoformat(time_value)
        except ValueError:
            continue
        route = fields.get("route", fields.get("endpoint", "?"))
        transport = fields.get("transport", "?")
        events.append(EaEvent(kind=kind, route=route, transport=transport, timestamp=timestamp,
                               detail=fields_text, source_file=str(path), source_line=line.strip()))
    return events


def _parse_bridge_console_log(path: Path) -> List[BridgeEvent]:
    return _parse_bridge_console_log_text(path.read_text(encoding="utf-8", errors="replace"), source=str(path))


def _parse_bridge_console_log_text(text: str, source: str = "<text>") -> List[BridgeEvent]:
    """Line-by-line, not one multi-line regex -- a single pattern spanning
    the whole block is fragile against optional lines (e.g. "Rejection
    reason:" only appears on non-2xx responses) shifting where later
    lines land; matching each line against its own fixed prefix is
    unambiguous regardless of which optional lines are present."""
    events: List[BridgeEvent] = []
    for block in text.split("=" * 48):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timestamp: Optional[datetime] = None
        path_value: Optional[str] = None
        reason: Optional[str] = None
        status: Optional[int] = None
        for line in lines:
            if line.startswith("[") and line.endswith("]") and timestamp is None:
                try:
                    timestamp = datetime.fromisoformat(line[1:-1])
                except ValueError:
                    pass
            elif line.startswith("Path: "):
                path_value = line[len("Path: "):].strip()
            elif line.startswith("Rejection reason: "):
                reason = line[len("Rejection reason: "):].strip()
            elif line.startswith("Response: "):
                try:
                    status = int(line[len("Response: "):].strip())
                except ValueError:
                    pass
        if timestamp is None or path_value is None or status is None:
            continue
        summary = f"[{timestamp.isoformat()}] Path: {path_value}, Response: {status}"
        if reason is not None:
            summary += f", Rejection reason: {reason}"
        events.append(BridgeEvent(
            timestamp=timestamp, transport="HTTP", route=path_value,
            rejection_reason=reason, response_status=status,
            source_file=source, source_line=summary,
        ))
    return events


_SOCKET_LOG_LINE_RE = re.compile(
    r"socket_transport: (?P<verdict>accepted|rejected) route=(?P<route>\S+) "
    r"status=(?P<status>\d+)(?: reason=(?P<reason>.+?))? remote=.+? now=(?P<now>\S+)"
)


def _parse_bridge_rotating_log(path: Path) -> List[BridgeEvent]:
    return _parse_bridge_rotating_log_lines(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), source=str(path),
    )


def _parse_bridge_rotating_log_lines(lines: List[str], source: str = "<lines>") -> List[BridgeEvent]:
    """Deliberately does not anchor to the `logging` module's own line
    prefix (e.g. `%(asctime)s %(levelname)-8s %(name)s: `) -- that prefix
    format is a formatter/handler configuration detail, not part of the
    log message itself, and differs between a real RotatingFileHandler
    line and, say, unittest.assertLogs' own default formatting. Only the
    message payload this module's own logger.info/warning calls produce
    is matched."""
    events: List[BridgeEvent] = []
    for line in lines:
        match = _SOCKET_LOG_LINE_RE.search(line)
        if not match:
            continue
        try:
            timestamp = datetime.fromisoformat(match.group("now"))
        except ValueError:
            continue
        events.append(BridgeEvent(
            timestamp=timestamp, transport="Socket", route=match.group("route"),
            rejection_reason=match.group("reason"), response_status=int(match.group("status")),
            source_file=source, source_line=line.strip(),
        ))
    return events


def _route_as_http_path(route: str) -> str:
    if route.startswith("/"):
        return route
    if route == _COMMANDS_POLL_ROUTE:
        return "/bridge/commands/poll"
    return _ROUTE_TO_HTTP_PATH.get(route, route)


def _find_matching_bridge_event(attempt: EaEvent, bridge_events: List[BridgeEvent], window: timedelta) -> Optional[BridgeEvent]:
    candidates = []
    for event in bridge_events:
        if attempt.transport == "HTTP" and event.transport != "HTTP":
            continue
        if attempt.transport == "Socket" and event.transport != "Socket":
            continue
        if attempt.transport == "HTTP":
            if event.route != _route_as_http_path(attempt.route):
                continue
        else:
            if event.route != attempt.route:
                continue
        delta = abs((event.timestamp - attempt.timestamp).total_seconds())
        if delta <= window.total_seconds():
            candidates.append((delta, event))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def _find_nearby_ea_outcome(attempt: EaEvent, ea_events: List[EaEvent], window: timedelta) -> Optional[EaEvent]:
    candidates = []
    for event in ea_events:
        if event.kind == "ATTEMPT":
            continue
        if event.transport != attempt.transport:
            continue
        delta = abs((event.timestamp - attempt.timestamp).total_seconds())
        if delta <= window.total_seconds():
            candidates.append((delta, event))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def _is_http_pseudo_status_no_response(outcome: EaEvent) -> bool:
    """True only for the EA's `TITAN_DIAG NO_RESPONSE transport=HTTP ...
    pseudoStatus=<n> ...` marker -- `HttpPost()`/`HttpGet()`'s own label
    for a `WebRequest()` return value outside the valid HTTP range
    (100-599). Never true for the Socket transport's own NO_RESPONSE
    marker (no `pseudoStatus` field there), which stays genuinely
    ambiguous (see its own comment in TitanProtocolEA.mq5)."""
    return outcome.transport == "HTTP" and "pseudoStatus=" in outcome.detail


@dataclass
class Classification:
    attempt: EaEvent
    state: str  # "1", "2", "3", "4", or "unmatched"
    mt5_attempted: str
    bridge_received: str
    auth_passed: str
    magic_number_matched: str
    validation_passed: str
    response_sent: str
    evidence: List[str]


def classify(attempt: EaEvent, ea_events: List[EaEvent], bridge_events: List[BridgeEvent], window: timedelta) -> Classification:
    evidence = [f"EA log: {attempt.source_file}: {attempt.source_line}"]
    bridge_match = _find_matching_bridge_event(attempt, bridge_events, window)
    if bridge_match is not None:
        evidence.append(f"Bridge log: {bridge_match.source_file}: {bridge_match.source_line}")
        auth, magic, validation = _subfields_for_reason(bridge_match.rejection_reason)
        state = "4" if bridge_match.rejection_reason is None else "3"
        return Classification(
            attempt=attempt, state=state, mt5_attempted=_YES, bridge_received=_YES,
            auth_passed=auth, magic_number_matched=magic, validation_passed=validation,
            response_sent=_YES, evidence=evidence,
        )
    outcome = _find_nearby_ea_outcome(attempt, ea_events, window)
    if outcome is not None and outcome.kind == "BLOCKED":
        evidence.append(f"EA log: {outcome.source_file}: {outcome.source_line}")
        return Classification(
            attempt=attempt, state="2", mt5_attempted=_YES, bridge_received=_NO,
            auth_passed=_NA, magic_number_matched=_NA, validation_passed=_NA, response_sent=_NO,
            evidence=evidence,
        )
    if outcome is not None and outcome.kind == "NO_RESPONSE" and _is_http_pseudo_status_no_response(outcome):
        # Runtime Audit Phase 4 -- a `pseudoStatus=` field on an HTTP
        # NO_RESPONSE marker is this EA's own honest label for a
        # WebRequest() return value outside the valid HTTP range (e.g.
        # 1001): the request never resulted in a real HTTP response from
        # this Bridge (which only ever returns 100-599), so -- unlike the
        # generic Socket-side NO_RESPONSE case below, where the frame
        # demonstrably left the process and genuine ambiguity remains --
        # this is classified directly and confidently as state 2, not
        # left unmatched.
        evidence.append(f"EA log: {outcome.source_file}: {outcome.source_line}")
        evidence.append(
            "EA's own NO_RESPONSE marker carries pseudoStatus= -- WebRequest() returned a value "
            "outside the valid HTTP range (100-599), which this Bridge never produces. This is "
            "a WinINet/transport-layer failure, not a Bridge response -- classified confidently "
            "as blocked before the Bridge, not left unmatched."
        )
        return Classification(
            attempt=attempt, state="2", mt5_attempted=_YES, bridge_received=_NO,
            auth_passed=_NA, magic_number_matched=_NA, validation_passed=_NA, response_sent=_NO,
            evidence=evidence,
        )
    if outcome is not None and outcome.kind == "NO_RESPONSE":
        evidence.append(f"EA log: {outcome.source_file}: {outcome.source_line}")
        evidence.append(
            "No BLOCKED marker and no matching Bridge log entry either -- the frame was sent, "
            "but whether the Bridge ever received it cannot be determined from this evidence "
            "alone (the reply may simply have been lost after the Bridge processed it)."
        )
        return Classification(
            attempt=attempt, state="unmatched", mt5_attempted=_YES, bridge_received=_UNKNOWN,
            auth_passed=_UNKNOWN, magic_number_matched=_UNKNOWN, validation_passed=_UNKNOWN,
            response_sent=_UNKNOWN, evidence=evidence,
        )
    evidence.append(
        "No BLOCKED/NO_RESPONSE marker and no matching Bridge log entry within the window -- "
        "most consistent with state 2 (blocked before the Bridge), but no explicit GetLastError "
        "evidence was found to confirm it; widen --window-seconds or re-check the scanned date."
    )
    return Classification(
        attempt=attempt, state="2", mt5_attempted=_YES, bridge_received=_NO,
        auth_passed=_NA, magic_number_matched=_NA, validation_passed=_NA, response_sent=_NO,
        evidence=evidence,
    )


_STATE_LABELS = {
    "1": "STATE 1 -- MT5 never attempted this request",
    "2": "STATE 2 -- MT5 attempted it, but it was blocked before reaching the Bridge",
    "3": "STATE 3 -- The Bridge received it and rejected it",
    "4": "STATE 4 -- The Bridge received it and accepted it",
    "unmatched": "UNRESOLVED -- evidence is genuinely ambiguous (see notes)",
}


def _print_classification(c: Classification) -> None:
    print("-" * 72)
    print(f"Route: {c.attempt.route}  Transport: {c.attempt.transport}  Attempted at: {c.attempt.timestamp.isoformat()}")
    print(f"Classification: {_STATE_LABELS[c.state]}")
    print(f"  MT5 attempted request:      {c.mt5_attempted}")
    print(f"  Bridge received request:    {c.bridge_received}")
    print(f"  Authentication passed:      {c.auth_passed}")
    print(f"  MagicNumber matched:        {c.magic_number_matched}")
    print(f"  Validation passed:          {c.validation_passed}")
    print(f"  Response sent:              {c.response_sent}")
    print("  Evidence:")
    for line in c.evidence:
        print(f"    - {line}")


def _locate_ea_log_files(data_folder: Path, dates: List[str]) -> List[Path]:
    logs_dir = data_folder / "MQL5" / "Logs"
    found = []
    for date in dates:
        candidate = logs_dir / f"{date}.log"
        if candidate.exists():
            found.append(candidate)
    return found


def _locate_bridge_console_log(log_dir: Path) -> Optional[Path]:
    candidate = log_dir / "bridge_console.log"
    return candidate if candidate.exists() else None


def _locate_newest_rotating_log(log_dir: Path) -> Optional[Path]:
    candidates = sorted(log_dir.glob("titan_protocol_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=str(_REPO_ROOT / "titan_protocol_config.json"))
    parser.add_argument("--window-seconds", type=float, default=10.0,
                         help="max seconds apart for an EA event and a Bridge log entry to be considered the same request (default 10)")
    parser.add_argument("--date", action="append", default=[],
                         help="YYYYMMDD date of the MT5 Experts log to scan (repeatable). Defaults to today and yesterday, local date -- "
                              "MT5 names its one-file-per-day logs by the terminal's local date, not UTC, and this script does not "
                              "assume which the operator's machine uses without being told.")
    parser.add_argument("--limit", type=int, default=20, help="max number of most recent attempts to classify and print (default 20)")
    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED to load configuration: {exc}", file=sys.stderr)
        return 2

    print(f"Titan Protocol communication classifier -- config: {config_path}")
    print()
    print("=== Step 1: resolve the running MT5 instance and Data Folder ===")
    report = mt5_terminal.build_resolution_report()
    print(report.describe())
    if report.unambiguous is None:
        print()
        print("Cannot proceed without exactly one resolved MT5 instance -- see verify_mt5_instance.py "
              "for the same resolution step with more detail. On this machine (no real MT5 install, "
              "e.g. this repository's own Linux sandbox) this always reports none/ambiguous by design.")
        return 2
    data_folder = report.unambiguous.data_folder
    print()

    dates = args.date or [datetime.now().strftime("%Y%m%d"), (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")]
    ea_log_files = _locate_ea_log_files(data_folder, dates)
    print("=== Step 2: locate the EA's Experts log (MQL5\\Logs\\<date>.log) ===")
    if not ea_log_files:
        print(f"No log file found for date(s) {dates} under {data_folder / 'MQL5' / 'Logs'}.")
    else:
        for f in ea_log_files:
            print(f"  Found: {f}")
    ea_events: List[EaEvent] = []
    for f in ea_log_files:
        ea_events.extend(_parse_ea_log(f))
    print(f"  {len(ea_events)} TITAN_DIAG line(s) parsed.")
    print()

    print("=== Step 3: locate the Bridge's own persisted logs ===")
    console_log = _locate_bridge_console_log(settings.log_dir)
    rotating_log = _locate_newest_rotating_log(settings.log_dir)
    bridge_events: List[BridgeEvent] = []
    if console_log is not None:
        print(f"  Found: {console_log}")
        bridge_events.extend(_parse_bridge_console_log(console_log))
    else:
        print(f"  {settings.log_dir / 'bridge_console.log'} not found -- has start.py been run since this fix was deployed?")
    if rotating_log is not None:
        print(f"  Found: {rotating_log}")
        bridge_events.extend(_parse_bridge_rotating_log(rotating_log))
    else:
        print(f"  No titan_protocol_*.log found under {settings.log_dir}.")
    print(f"  {len(bridge_events)} Bridge request record(s) parsed.")
    print()

    attempts = sorted((e for e in ea_events if e.kind == "ATTEMPT"), key=lambda e: e.timestamp)
    print("=== Step 4: classify every attempt found ===")
    if not attempts:
        print("No TITAN_DIAG ATTEMPT lines found in the scanned window -- STATE 1 for every route: "
              "MT5 never attempted a request in this window (per the file(s) listed in Step 2, which "
              "is the complete, disclosed set searched, not a guess about an unexamined file).")
        return 1

    window = timedelta(seconds=args.window_seconds)
    classifications = [classify(a, ea_events, bridge_events, window) for a in attempts[-args.limit:]]
    for c in classifications:
        _print_classification(c)

    print("-" * 72)
    unresolved = [c for c in classifications if c.state in ("1", "2", "unmatched")]
    print(f"{len(classifications)} attempt(s) classified; {len(unresolved)} did not reach STATE 3/4 (Bridge received).")
    return 0 if not unresolved else 1


if __name__ == "__main__":
    sys.exit(main())

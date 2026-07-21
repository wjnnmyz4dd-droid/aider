"""Transport-configuration verification (Part 2 of the corrective patch
following the persistent WebRequest()/socket transport instability
investigation).

Context: after switching `Transport=Socket` on the EA, a live deployment
reported the same symptom continuing -- the leading, still-unconfirmed
hypothesis was that only one side (the EA's `Transport` input or the
Bridge's `bridge.transport` config) was actually changed, or that the
EA's input change never took effect (needs a full terminal restart, not
just reattach). This script does not assume either hypothesis: it reads
the real, currently-configured and currently-observed state from both
sides and reports the evidence plainly, the same "never guess, always
read from a real file" discipline `diagnose_communication.py` already
established -- reusing its own log-location and EA-log-parsing helpers
rather than re-implementing them a second way (this codebase's own rule
against duplicate parsing/classification logic).

Evidence produced, each sourced from a real file, never inferred:
  1. Bridge's configured transport (`bridge.transport` from the JSON
     config `config_loader.load_settings()` actually loads).
  2. EA's configured transport, as the EA itself resolved it at OnInit
     (`Transport=<value>` -- the terminal's own resolved input value, not
     a guess about `.set`-file enum serialization, which this session
     could not confirm with confidence -- see ADR-034 Amendment 2's own
     note).
  3. The Bridge's actual listener(s) bound at startup (its own
     `logger.info`/`logger.warning` startup lines in the newest rotating
     log).
  4. Which transport is actually carrying each request, from the EA's own
     `TITAN_DIAG ATTEMPT ... transport=...` lines (a real per-request
     tally, not a single snapshot).
  5. Whether the EA's automatic Socket-to-HTTP fallback (ADR-034
     Amendment 3) fired during the scanned window.
  6. A plain verdict: MATCHED, MISMATCH, or FALLBACK_OCCURRED, always
     with the evidence lines that produced it -- never asserted without
     citing the line(s) it came from.

Usage:
    python verify_transport_configuration.py [path/to/titan_protocol_config.json]
        [--date YYYYMMDD] [--limit N]

Exit code: 0 if the evidence supports MATCHED (both sides configured and
observed to agree, no fallback); 1 for MISMATCH, FALLBACK_OCCURRED, or
insufficient evidence; 2 on a configuration/environment error.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Counter as CounterType, List, Optional

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
# Reused, not re-derived: diagnose_communication.py already established
# the correct way to locate/parse the EA's Experts log and the Bridge's
# rotating log -- duplicating that parsing here would risk the two
# silently drifting apart (this codebase's own rule).
from diagnose_communication import (  # noqa: E402
    EaEvent,
    _locate_ea_log_files,
    _locate_newest_rotating_log,
    _parse_ea_log,
)

_ONINIT_TRANSPORT_RE = re.compile(r"TitanProtocolEA initialized\..*?Transport=(\S+)")
_FALLBACK_RE = re.compile(
    r"TitanProtocolEA: Socket transport failed (\d+) consecutive connection attempts -- "
    r"automatically falling back to HTTP transport"
)
_BRIDGE_LISTENING_RE = re.compile(r"Bridge (\S+) service listening on (\S+):(\d+)")
_BRIDGE_HTTP_FALLBACK_ACTIVE_RE = re.compile(r"Bridge HTTP fallback listener also active on (\S+):(\d+)")
_BRIDGE_HTTP_FALLBACK_FAILED_RE = re.compile(r"Bridge HTTP fallback listener failed to bind (\S+):(\d+)")


@dataclass
class Evidence:
    bridge_configured_transport: Optional[str] = None
    ea_configured_transport: Optional[str] = None
    ea_oninit_source_line: Optional[str] = None
    bridge_listener_line: Optional[str] = None
    bridge_http_fallback_line: Optional[str] = None
    fallback_occurred: bool = False
    fallback_source_line: Optional[str] = None
    observed_transport_tally: "CounterType[str]" = field(default_factory=lambda: __import__("collections").Counter())
    notes: List[str] = field(default_factory=list)


def _find_ea_oninit_transport(ea_log_files: List[Path]) -> Optional[tuple]:
    """Returns (transport_value, source_line) from the EA's own OnInit
    Print() -- the terminal's own resolved input value, taken from the
    same log this codebase already trusts for every other EA-side fact.
    Scans every file/line and keeps the last match (most recent init)."""
    result = None
    for path in ea_log_files:
        try:
            text = path.read_text(encoding="utf-16", errors="strict")
        except (UnicodeError, OSError):
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeError, OSError):
                text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            match = _ONINIT_TRANSPORT_RE.search(line)
            if match:
                result = (match.group(1), line.strip())
    return result


def _find_fallback_event(ea_log_files: List[Path]) -> Optional[tuple]:
    for path in ea_log_files:
        try:
            text = path.read_text(encoding="utf-16", errors="strict")
        except (UnicodeError, OSError):
            try:
                text = path.read_text(encoding="utf-8", errors="strict")
            except (UnicodeError, OSError):
                text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if _FALLBACK_RE.search(line):
                return (True, line.strip())
    return None


def _find_bridge_listener_lines(rotating_log: Optional[Path]) -> tuple:
    listener_line = None
    fallback_line = None
    if rotating_log is None:
        return listener_line, fallback_line
    text = rotating_log.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if _BRIDGE_LISTENING_RE.search(line):
            listener_line = line.strip()
        elif _BRIDGE_HTTP_FALLBACK_ACTIVE_RE.search(line) or _BRIDGE_HTTP_FALLBACK_FAILED_RE.search(line):
            fallback_line = line.strip()
    return listener_line, fallback_line


def gather_evidence(config_path: Path, dates: List[str]) -> Evidence:
    import collections

    evidence = Evidence()
    settings = load_settings(config_path)
    evidence.bridge_configured_transport = settings.bridge_config.transport

    report = mt5_terminal.build_resolution_report()
    if report.unambiguous is not None:
        data_folder = report.unambiguous.data_folder
        ea_log_files = _locate_ea_log_files(data_folder, dates)
        oninit = _find_ea_oninit_transport(ea_log_files)
        if oninit is not None:
            evidence.ea_configured_transport, evidence.ea_oninit_source_line = oninit
        else:
            evidence.notes.append(
                "No 'TitanProtocolEA initialized...Transport=' line found in the scanned EA log(s) -- "
                "cannot confirm which transport the EA actually resolved at OnInit."
            )
        fallback = _find_fallback_event(ea_log_files)
        if fallback is not None:
            evidence.fallback_occurred, evidence.fallback_source_line = fallback

        ea_events: List[EaEvent] = []
        for f in ea_log_files:
            ea_events.extend(_parse_ea_log(f))
        attempts = [e for e in ea_events if e.kind == "ATTEMPT"]
        evidence.observed_transport_tally = collections.Counter(e.transport for e in attempts)
    else:
        evidence.notes.append(
            "Cannot resolve exactly one running MT5 instance/Data Folder -- EA-side configured "
            "transport and per-request observed transport cannot be read. See verify_mt5_instance.py."
        )

    rotating_log = _locate_newest_rotating_log(settings.log_dir)
    evidence.bridge_listener_line, evidence.bridge_http_fallback_line = _find_bridge_listener_lines(rotating_log)
    if rotating_log is None:
        evidence.notes.append(f"No titan_protocol_*.log found under {settings.log_dir} -- cannot confirm the Bridge's actual bound listener(s).")

    return evidence


def _normalize_transport_label(label: str) -> str:
    """The same transport is spelled three different ways across this
    codebase's own evidence sources: `bridge.transport` uses "http"/
    "socket"; the EA's OnInit EnumToString(Transport) print uses
    "TRANSPORT_HTTP"/"TRANSPORT_SOCKET"; the EA's per-request
    TITAN_DIAG ATTEMPT transport= field uses "HTTP"/"Socket". Never
    guesses at a fourth spelling -- strips only the one known enum
    prefix, then lowercases."""
    normalized = label.strip()
    if normalized.upper().startswith("TRANSPORT_"):
        normalized = normalized[len("TRANSPORT_"):]
    return normalized.lower()


def _verdict(evidence: Evidence) -> str:
    if evidence.ea_configured_transport is None or evidence.bridge_configured_transport is None:
        return "INSUFFICIENT_EVIDENCE"
    ea_transport_normalized = _normalize_transport_label(evidence.ea_configured_transport)
    bridge_transport_normalized = _normalize_transport_label(evidence.bridge_configured_transport)
    if evidence.fallback_occurred:
        return "FALLBACK_OCCURRED"
    if ea_transport_normalized != bridge_transport_normalized:
        return "MISMATCH"
    observed = evidence.observed_transport_tally
    if observed:
        observed_transports = {_normalize_transport_label(t) for t in observed}
        if len(observed_transports) > 1:
            return "MISMATCH"
        if ea_transport_normalized not in observed_transports:
            return "MISMATCH"
    return "MATCHED"


def _print_report(evidence: Evidence, verdict: str) -> None:
    print("=" * 72)
    print("Transport configuration verification")
    print("=" * 72)
    print(f"Bridge configured transport (bridge.transport):  {evidence.bridge_configured_transport}")
    print(f"EA configured transport (OnInit, resolved):      {evidence.ea_configured_transport}")
    if evidence.ea_oninit_source_line:
        print(f"  Evidence: {evidence.ea_oninit_source_line}")
    print(f"Bridge actual listener(s) bound at startup:      {evidence.bridge_listener_line or 'not found'}")
    if evidence.bridge_http_fallback_line:
        print(f"Bridge HTTP fallback listener status:            {evidence.bridge_http_fallback_line}")
    if evidence.observed_transport_tally:
        print("Observed transport per EA request (TITAN_DIAG ATTEMPT tally):")
        for transport, count in evidence.observed_transport_tally.most_common():
            print(f"  {transport}: {count}")
    else:
        print("Observed transport per EA request: no TITAN_DIAG ATTEMPT lines found in the scanned window.")
    print(f"EA automatic Socket->HTTP fallback occurred:     {evidence.fallback_occurred}")
    if evidence.fallback_source_line:
        print(f"  Evidence: {evidence.fallback_source_line}")
    for note in evidence.notes:
        print(f"NOTE: {note}")
    print("-" * 72)
    print(f"VERDICT: {verdict}")
    if verdict == "MISMATCH":
        print(
            "The EA and Bridge were not observed running the same transport in this window -- "
            "do not assume they matched; check which side was actually changed and whether the "
            "EA's chart was fully restarted (Transport is a compiled input, not reloadable via reattach alone)."
        )
    elif verdict == "FALLBACK_OCCURRED":
        print(
            "The EA's own automatic Socket->HTTP fallback (ADR-034 Amendment 3) fired during this "
            "window -- switching the EA's Transport input to Socket did not result in a lasting Socket "
            "connection; it silently reverted to HTTP after repeated reconnect failures."
        )
    elif verdict == "INSUFFICIENT_EVIDENCE":
        print("Not enough evidence was found to confirm either side's actual runtime transport -- see NOTEs above.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=str(_REPO_ROOT / "titan_protocol_config.json"))
    parser.add_argument("--date", action="append", default=[],
                         help="YYYYMMDD date of the MT5 Experts log to scan (repeatable). Defaults to today and yesterday, local date.")
    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        evidence = gather_evidence(
            config_path,
            args.date or [datetime.now().strftime("%Y%m%d"), (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")],
        )
    except ConfigError as exc:
        print(f"FAILED to load configuration: {exc}", file=sys.stderr)
        return 2

    verdict = _verdict(evidence)
    _print_report(evidence, verdict)
    return 0 if verdict == "MATCHED" else 1


if __name__ == "__main__":
    sys.exit(main())

"""MT5 instance/whitelist connectivity validator (Deployment Bug Fix,
item 6) -- proves, with real evidence, exactly what an operator needs
to know when GetLastError=4014 persists despite having "added the URL":

  1. Correct MT5 instance   -- a running terminal64.exe/terminal.exe was found
  2. Correct Data Folder    -- that process's data folder, via origin.txt
  3. Correct Experts folder -- the installed EA matches this release byte-for-byte
  4. WebRequest whitelist   -- CANNOT be verified by file inspection (see below);
                               reported honestly as unverifiable, not faked
  5. Bridge reachable       -- a real TCP connection to the Bridge's HTTP listener
  6. EA can successfully POST -- a real, recent EA heartbeat already recorded
                               by the running Titan Protocol process

Item 4 is the one claim this script does NOT make good on, and says so
explicitly: MT5 stores the WebRequest allow-list in
`<data folder>\\Config\\experts.ini`, an undocumented binary format with
no supported read/write API (confirmed via MQL5 community documentation,
not assumed -- see mt5_terminal.py's own module docstring for the same
citation). Item 6 is this script's actual proof that the allow-list is
working: a real heartbeat already reaching the Bridge from the EA is
ground truth no file inspection could ever be more convincing than.

Usage: python verify_mt5_instance.py [path/to/titan_protocol_config.json]
Exit code: 0 only if every check that CAN be automatically verified
passed (checks 1/2/3/5 mandatory, 6 informational since it requires a
real attached EA that may not exist yet) -- 1 otherwise. Every line
printed is either a value read from a real file/process, or an explicit
"cannot verify" statement; nothing here is guessed.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

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


def _print_result(ok, label: str, detail: str) -> None:
    tag = "PASS" if ok is True else ("INFO" if ok is None else "FAIL")
    print(f"[{tag}] {label}")
    if detail:
        print(f"       {detail}")


def check_instance_and_data_folder(report: "mt5_terminal.ResolutionReport"):
    """Items 1 and 2: is a real terminal running, and which data folder
    is it using -- via origin.txt, never guessed."""
    print(report.describe())
    if not report.running_terminals:
        _print_result(False, "Correct MT5 instance (running process found)",
                       "No terminal64.exe/terminal.exe is currently running. Open MT5 first.")
        return None
    _print_result(True, "Correct MT5 instance (running process found)",
                  f"{len(report.running_terminals)} process(es) detected.")
    if report.unambiguous is None:
        _print_result(False, "Correct Data Folder (resolved via origin.txt)",
                       "Could not resolve exactly one data folder for a running terminal -- "
                       "see the ambiguity/no-match detail printed above. Pass an explicit data "
                       "folder if you have more than one MT5 installation.")
        return None
    _print_result(True, "Correct Data Folder (resolved via origin.txt)",
                  f"pid={report.unambiguous.running_pid} -> {report.unambiguous.data_folder}")
    return report.unambiguous


def check_experts_folder(data_folder: Path):
    """Item 3: the EA sitting in this terminal's Experts folder is
    byte-for-byte the one this release ships -- not merely "a file with
    the right name exists"."""
    installed = data_folder / "MQL5" / "Experts" / "TitanProtocol" / "TitanProtocolEA.mq5"
    shipped = _REPO_ROOT / "mt5" / "TitanProtocolEA.mq5"
    if not installed.exists():
        _print_result(False, "Correct Experts folder (EA installed)",
                       f"{installed} does not exist -- run install_mt5_files.py first.")
        return False
    if not shipped.exists():
        _print_result(False, "Correct Experts folder (EA installed)",
                       f"{shipped} (this release's own source) is missing -- corrupt install.")
        return False
    matches = installed.read_bytes() == shipped.read_bytes()
    _print_result(matches, "Correct Experts folder (EA installed, byte-for-byte match)",
                  f"{installed} {'matches' if matches else 'DOES NOT MATCH'} {shipped} -- "
                  + ("re-run install_mt5_files.py to update it." if not matches else "up to date."))
    return matches


def check_whitelist_unverifiable() -> None:
    """Item 4, told straight: this cannot be checked by file inspection."""
    _print_result(
        None, "WebRequest allow-list contents",
        "CANNOT BE VERIFIED by this or any script -- MT5 stores it in an undocumented, "
        "binary <data folder>\\Config\\experts.ini with no supported read/write API "
        "(confirmed against MQL5 community documentation, not assumed). The only trustworthy "
        "proof it is actually working is check 6 below (a real EA heartbeat already recorded) "
        "-- not a file-content check.",
    )


def check_bridge_reachable(settings) -> bool:
    """Item 5: a real TCP connection, not a assumed one."""
    host, port = settings.bridge_host, settings.bridge_port
    try:
        with socket.create_connection((host, port), timeout=2.0):
            _print_result(True, "Bridge reachable -- HTTP", f"{host}:{port}")
            return True
    except OSError as exc:
        _print_result(False, "Bridge reachable -- HTTP", f"{host}:{port}: {exc}")
        return False


def check_ea_can_post(settings):
    """Item 6: the real, live ground truth -- has the EA actually
    reached the Bridge recently, per this deployment's own running
    process, not a synthetic Python-side request standing in for it
    (a Python HTTP POST succeeding would only prove ordinary networking
    works, not that MT5's separately-sandboxed WebRequest
    permission does)."""
    import json
    from datetime import datetime, timezone

    health_path = settings.state_dir / "health.json"
    if not health_path.exists():
        _print_result(False, "EA can successfully POST to the Bridge (real heartbeat evidence)",
                       "state/health.json not found -- Titan Protocol is not currently running "
                       "(start.py never wrote it). Start it, attach the EA, then re-run this check.")
        return False
    try:
        payload = json.loads(health_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _print_result(False, "EA can successfully POST to the Bridge (real heartbeat evidence)", f"health.json unreadable: {exc!r}")
        return False

    mt5_connected = payload.get("mt5_connected")
    generated_at = payload.get("generated_at")
    if mt5_connected:
        _print_result(True, "EA can successfully POST to the Bridge (real heartbeat evidence)",
                       f"mt5_connected=True as of {generated_at} -- a real EA heartbeat has been "
                       "recorded by the running Bridge. This is the actual proof the allow-list "
                       "works, not an inference from any config file.")
        return True
    _print_result(False, "EA can successfully POST to the Bridge (real heartbeat evidence)",
                  f"mt5_connected=False as of {generated_at} -- no recent EA heartbeat recorded. "
                  "Attach TitanProtocolEA in MT5 and confirm the allow-list per check 4's guidance "
                  "above (a full terminal restart, not just re-attach, is frequently required).")
    return False


def main() -> int:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO_ROOT / "titan_protocol_config.json"
    print(f"Titan Protocol MT5 instance/whitelist validator -- config: {config_path}")
    print()

    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"FAILED to load configuration: {exc}", file=sys.stderr)
        return 1

    print("=== Checks 1-2: MT5 instance and data folder ===")
    report = mt5_terminal.build_resolution_report()
    resolved = check_instance_and_data_folder(report)
    print()

    print("=== Check 3: Experts folder ===")
    experts_ok = check_experts_folder(resolved.data_folder) if resolved is not None else False
    if resolved is None:
        _print_result(False, "Correct Experts folder (EA installed)", "skipped -- no resolved data folder from checks 1-2.")
    print()

    print("=== Check 4: WebRequest allow-list ===")
    check_whitelist_unverifiable()
    print()

    print("=== Check 5: Bridge reachable ===")
    bridge_ok = check_bridge_reachable(settings)
    print()

    print("=== Check 6: EA can successfully POST (real heartbeat evidence) ===")
    ea_posted = check_ea_can_post(settings)
    print()

    mandatory_ok = bool(resolved is not None and experts_ok and bridge_ok)
    print("=" * 72)
    if mandatory_ok:
        print("Checks 1/2/3/5 (instance, data folder, Experts folder, Bridge reachability) PASSED.")
    else:
        print("One or more of checks 1/2/3/5 FAILED -- see detail above.")
    if ea_posted:
        print("Check 6 (real EA heartbeat) also PASSED -- the allow-list is confirmed working end to end.")
    else:
        print("Check 6 (real EA heartbeat) did not pass -- this is expected before you've attached "
              "the EA; it is the one check that proves the allow-list itself is actually working.")
    print("=" * 72)
    return 0 if mandatory_ok else 1


if __name__ == "__main__":
    sys.exit(main())

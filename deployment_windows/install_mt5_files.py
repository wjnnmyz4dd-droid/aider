"""Titan Protocol MT5 file installer (Python Deployment Manager).

Locates (or asks for) the active MT5 data folder, copies
TitanProtocolEA.mq5 into MQL5/Experts/TitanProtocol/ and a *personalized*
TitanProtocolEA.set (ApiKey/MagicNumber/BackendUrl/AllowedSymbolsCsv
filled in from titan_protocol_config.json, when available) into
MQL5/Presets/TitanProtocol/, taking a timestamped backup of any file it
would otherwise overwrite. Does NOT compile the .mq5 -- that step can
only happen inside MetaEditor on the real Windows/MT5 installation;
this script prints the exact steps to do it and does not claim to
have done it itself.

Usage: python install_mt5_files.py ["C:\\path\\to\\MT5\\data\\folder"]
  If no path is given, this script uses mt5_terminal.py to try to
  resolve exactly one CURRENTLY RUNNING terminal instance (not merely
  "a folder that looks like MT5 data" -- see mt5_terminal.py's own
  docstring for why this distinction matters and what it can/cannot
  verify) and asks you to confirm/choose if more than one (or none) is
  found running.

Deployment-bug fix (GetLastError=4014 despite the operator having added
the Bridge address to the allow-list): MT5's WebRequest
allow-list lives in an undocumented, binary `<data folder>\\Config\\
experts.ini` -- there is no supported way for this script to read or
write its contents (confirmed via MQL5 community documentation before
writing this comment, not assumed). What this script CAN do, and now
does, is remove every OTHER source of ambiguity that produces this
exact symptom: which of several installed terminals is actually
running, which data folder that running terminal is using, and whether
the EA files just copied are really the ones sitting in that terminal's
Experts folder. See `verify_mt5_instance.py` for the corresponding
verification script and WINDOWS_OPERATOR_GUIDE.md for the operator-facing
explanation of why a restart of the terminal (not just re-attaching the
EA) is frequently required after changing the allow-list.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import mt5_terminal  # noqa: E402


def _find_repo_root(here: Path) -> Path:
    """Locates the installation root -- the folder containing both
    titan_protocol/ and mt5/ -- whether this script lives directly inside it
    (the shipped, flattened C:\\TitanProtocol\\install_mt5_files.py layout) or
    one level below it (this repository's own deployment_windows/
    subfolder, used for development)."""
    for candidate in (here, here.parent):
        if (candidate / "titan_protocol").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Titan Protocol installation root (a folder containing "
        f"both titan_protocol/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


_REPO_ROOT = _find_repo_root(_HERE)
_SOURCE_DIR = _REPO_ROOT / "mt5"

# .set files are plain `key=value` text (see mt5/TitanProtocolEA.set) --
# these are the keys install.py's auto-generated config has real values
# for. Every other line in the shipped template (comments, the less
# safety-critical tuning knobs) passes through unchanged.
_PERSONALIZABLE_KEYS = ("ApiKey", "MagicNumber", "BackendUrl", "AllowedSymbolsCsv")


def _find_mt5_data_dirs() -> list:
    """Fallback only -- every folder that merely LOOKS like MT5 data
    (has an MQL5\\ subfolder), with no cross-check against which
    terminal is actually running. Used only when mt5_terminal.py
    can't detect any running terminal process at all (e.g. PowerShell
    unavailable) -- resolve_mt5_data_dir() always prefers the
    confirmed-running match when one exists."""
    return [folder.path for folder in mt5_terminal.discover_data_folders()]


def _resolve_mt5_data_dir(explicit_path: str, non_interactive: bool) -> Optional[Path]:
    """Returns None (never raises) when running non-interactively and
    the folder can't be resolved without a human choosing -- callers
    like install.py treat that as "skipped, not fatal" rather than
    aborting the whole installation over an MT5-side ambiguity.

    Prefers mt5_terminal.py's running-instance resolution (item 1/2/3
    of the deployment-bug fix: which terminal is actually running,
    whether more than one is, whether the data folder we're about to
    write into is the one that instance is using) over the old
    "any folder that looks like MT5 data" heuristic -- the latter is
    kept only as an explicit, clearly-labeled fallback for when no
    running terminal process could be detected at all."""
    if explicit_path:
        path = Path(explicit_path)
        if not (path / "MQL5").exists():
            print(f"FAILED: {path}\\MQL5 does not exist -- this does not look like a valid MT5 data folder.", file=sys.stderr)
            if non_interactive:
                return None
            raise SystemExit(2)
        report = mt5_terminal.build_resolution_report()
        matches_running = any(mt5_terminal.paths_equal(r.data_folder, path) for r in report.resolved)
        if report.running_terminals and not matches_running:
            print(
                f"WARNING: {path} does not match any currently-running MT5 terminal process. "
                "The whitelist you configure must be in the terminal that is ACTUALLY RUNNING, "
                "not merely a data folder that happens to exist on disk. Evidence:\n" + report.describe(),
                file=sys.stderr,
            )
        return path

    print("No MT5 data folder given -- resolving the currently-running MT5 terminal instance...")
    report = mt5_terminal.build_resolution_report()
    print(report.describe())

    if report.unambiguous is not None:
        found = report.unambiguous.data_folder
        print(f"\nRESOLVED (confirmed running): pid={report.unambiguous.running_pid} -> {found}")
        if non_interactive:
            return found
        confirm = input("Use this folder? [Y/n]: ").strip().lower()
        if confirm == "n":
            print("Aborted -- re-run with the correct path as an argument.")
            raise SystemExit(1)
        return found

    if len(report.resolved) > 1:
        print("\nAMBIGUOUS: more than one running MT5 terminal was matched to a data folder --"
              " an explicit data folder argument is required so the right one is chosen, not guessed:")
        for r in report.resolved:
            print(f'  python install_mt5_files.py "{r.data_folder}"   (pid={r.running_pid}, {r.running_exe_path})')
        if non_interactive:
            return None
        raise SystemExit(2)

    # No running terminal could be matched at all -- fall back to the
    # old, weaker heuristic (folders that merely look like MT5 data),
    # clearly labeled as unconfirmed since we could not verify any of
    # them is the one actually running.
    candidates = _find_mt5_data_dirs()
    if not candidates:
        if non_interactive:
            print("No MT5 terminal data folder was auto-detected -- skipping MT5 file install "
                  "(open MT5 at least once, then re-run install_mt5_files.py).")
            return None
        entered = input("No MT5 terminal data folder was auto-detected. Enter the full path to your MT5 data folder (the one containing MQL5\\): ").strip()
        if not entered:
            print("FAILED: no path given.", file=sys.stderr)
            raise SystemExit(2)
        return _resolve_mt5_data_dir(entered, non_interactive)

    if len(candidates) > 1:
        print("More than one MT5 terminal data folder exists on disk (none confirmed running):")
        for candidate in candidates:
            print(f"  {candidate}")
        if non_interactive:
            print("Skipping automatic MT5 file install -- re-run install_mt5_files.py with "
                  "the correct one as an argument, e.g.:")
            print(f'  python install_mt5_files.py "{candidates[0]}"')
            return None
        print("Re-run this script with the correct one as an argument, e.g.:")
        print(f'  python install_mt5_files.py "{candidates[0]}"')
        raise SystemExit(2)

    found = candidates[0]
    print(f"Exactly one MT5 terminal data folder exists on disk (not confirmed running -- "
          f"MT5 may not be started yet): {found}")
    if non_interactive:
        return found
    confirm = input("Use this folder? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Aborted -- re-run with the correct path as an argument.")
        raise SystemExit(1)
    return found


def _backup_if_exists(path: Path) -> None:
    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(path.name + f".bak_{timestamp}")
        print(f"Existing {path.name} found -- backing it up to {backup_path.name} first.")
        shutil.copy2(path, backup_path)


def _write_personalized_set(source_path: Path, dest_path: Path, personalize: dict) -> None:
    """Rewrites the shipped .set template, filling in the keys named in
    `personalize` (a subset of _PERSONALIZABLE_KEYS) so the operator
    doesn't have to type them into MT5's EA settings dialog by hand --
    every other line (comments, other tuning knobs) is copied through
    unchanged."""
    lines = source_path.read_text(encoding="utf-8").splitlines()
    out_lines = []
    seen = set()
    for line in lines:
        stripped = line.strip()
        matched_key = None
        if stripped and not stripped.startswith(";") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in personalize:
                matched_key = key
        if matched_key:
            out_lines.append(f"{matched_key}={personalize[matched_key]}")
            seen.add(matched_key)
        else:
            out_lines.append(line)
    for key, value in personalize.items():
        if key not in seen:
            out_lines.append(f"{key}={value}")
    dest_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")


def run(
    explicit_mt5_dir: str = "",
    non_interactive: bool = False,
    personalize: Optional[dict] = None,
    bridge_address: str = "",
    whitelist_confirmed: bool = False,
) -> int:
    """Returns 0 on success, 2 on a hard failure (missing source files,
    an explicitly-given path that isn't a valid MT5 data folder), 3
    when the MT5 data folder couldn't be resolved non-interactively
    (not fatal -- the rest of installation still proceeds; see
    install.py, which treats 3 as "skipped, report it, keep going"),
    and 4 when the files were copied successfully but the operator has
    not confirmed the WebRequest allow-list is set in the
    correct, currently-running terminal (deployment-bug fix, item 5:
    stop with a clear error rather than silently continuing -- see
    module docstring for why this can't be a genuine file-content
    check)."""
    mq5_source = _SOURCE_DIR / "TitanProtocolEA.mq5"
    set_source = _SOURCE_DIR / "TitanProtocolEA.set"
    if not mq5_source.exists():
        print(f"FAILED: {mq5_source} not found.", file=sys.stderr)
        return 2
    if not set_source.exists():
        print(f"FAILED: {set_source} not found.", file=sys.stderr)
        return 2

    mt5_data_dir = _resolve_mt5_data_dir(explicit_mt5_dir, non_interactive)
    if mt5_data_dir is None:
        return 3

    experts_dir = mt5_data_dir / "MQL5" / "Experts" / "TitanProtocol"
    presets_dir = mt5_data_dir / "MQL5" / "Presets" / "TitanProtocol"
    experts_dir.mkdir(parents=True, exist_ok=True)
    presets_dir.mkdir(parents=True, exist_ok=True)

    mq5_dest = experts_dir / "TitanProtocolEA.mq5"
    _backup_if_exists(mq5_dest)
    shutil.copy2(mq5_source, mq5_dest)
    print(f"Copied TitanProtocolEA.mq5 to {experts_dir}")

    set_dest = presets_dir / "TitanProtocolEA.set"
    _backup_if_exists(set_dest)
    if personalize:
        _write_personalized_set(set_source, set_dest, personalize)
        print(f"Wrote a personalized TitanProtocolEA.set to {presets_dir} "
              f"({', '.join(sorted(personalize))} filled in from titan_protocol_config.json)")
    else:
        shutil.copy2(set_source, set_dest)
        print(f"Copied TitanProtocolEA.set to {presets_dir} (unpersonalized -- "
              "edit ApiKey/MagicNumber by hand before loading it in MT5)")

    # Item 3 of the deployment-bug fix: prove (not assume) the file we
    # just copied is really sitting in the Experts folder of the SAME
    # terminal instance mt5_data_dir was resolved from -- a byte-for-byte
    # comparison against the shipped source, not merely "the copy call
    # didn't raise."
    installed_matches_source = mq5_dest.read_bytes() == mq5_source.read_bytes()
    print(
        f"Verified installed EA matches shipped source (byte-for-byte): {installed_matches_source} "
        f"-- {mq5_dest}"
    )

    print()
    print("=" * 60)
    print("Files copied. Compilation is NOT done by this script -- it can")
    print("only happen inside MetaEditor on this real Windows/MT5")
    print("installation. Do this next:")
    print()
    print("  1. Open MetaEditor (from MT5: Tools > MetaQuotes Language Editor,")
    print("     or press F4 inside MT5).")
    print("  2. In MetaEditor's Navigator panel, expand Experts > TitanProtocol")
    print("     and double-click TitanProtocolEA.mq5 to open it.")
    print("  3. Press F7 (or the Compile toolbar button) to compile.")
    print('  4. Confirm the status/output window shows "0 error(s)" -- a')
    print("     TitanProtocolEA.ex5 file will appear next to the .mq5 file")
    print(f"     in {experts_dir} only once compilation succeeds.")
    print("  5. Back in MT5, refresh the Navigator panel (right-click >")
    print("     Refresh) so the compiled EA appears under")
    print("     Expert Advisors > Titan Protocol > TitanProtocolEA.")
    print()
    print("This script has NOT compiled the EA and has NOT verified MT5")
    print("connectivity -- both require the real MetaEditor/MT5 GUI, which")
    print("is outside what a Python script can do.")
    print("=" * 60)

    # Items 4/5 of the deployment-bug fix. MT5's WebRequest
    # allow-list lives in an undocumented, binary <data folder>\Config\
    # experts.ini -- there is no supported way to read or write it from
    # here (see module docstring). Rather than silently assume it is
    # correct (the exact bug being fixed: "URLs have been added" yet
    # GetLastError=4014 persists), this step requires an explicit,
    # logged operator attestation naming the EXACT resolved terminal
    # instance, and stops installation with a clear error if it is
    # withheld -- it does not silently continue.
    address = bridge_address or "the Bridge address shown in titan_protocol_config.json"
    print()
    print("-" * 60)
    print("WHITELIST CONFIRMATION REQUIRED (deployment-bug fix)")
    print("-" * 60)
    print(f"MT5's allow-list (Tools > Options > Expert Advisors) must contain {address}")
    print(f"in THIS EXACT terminal's data folder: {mt5_data_dir}")
    print("A very common cause of GetLastError=4014 persisting even after adding the URL:")
    print("the allow-list change does not take effect for an already-attached EA, and in")
    print("many MT5 builds not even for a re-attached one -- a FULL terminal restart")
    print("(close MT5 completely, then reopen) is frequently required, not just re-attach.")
    print("MT5 does not expose a supported way for this installer to verify the allow-list's")
    print("contents itself (it is stored in an undocumented, binary experts.ini) -- see")
    print("verify_mt5_instance.py for the real, live end-to-end proof (Bridge reachability")
    print("+ an actual recent EA heartbeat) once you believe this is done.")
    print("-" * 60)
    if not whitelist_confirmed:
        if non_interactive:
            print(
                "FAILED: whitelist confirmation not given -- refusing to consider MT5 setup "
                "complete. Re-run with whitelist_confirmed=True (install.py: "
                "--whitelist-confirmed) once you have added the address above to the terminal "
                f"at {mt5_data_dir} and fully restarted it.",
                file=sys.stderr,
            )
            return 4
        answer = input(
            f"Have you added {address} to Tools>Options>Expert Advisors in the terminal at "
            f"{mt5_data_dir}, AND fully restarted MT5 (not just re-attached the EA) since? [y/N]: "
        ).strip().lower()
        if answer != "y":
            print("Aborted -- complete the allow-list step above, then re-run this script.", file=sys.stderr)
            return 4
    print("Whitelist confirmed by operator for this terminal instance.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Titan Protocol's MT5 EA files")
    parser.add_argument("mt5_data_dir", nargs="?", default="", help="path to the MT5 data folder (auto-detected if omitted)")
    parser.add_argument(
        "--whitelist-confirmed", action="store_true",
        help="confirm you have added the Bridge address to Tools>Options>Expert Advisors in the "
             "resolved terminal AND fully restarted it -- required to complete non-interactively "
             "(deployment-bug fix, item 5: refuses to silently continue without this)",
    )
    parser.add_argument("--bridge-address", default="", help="the address to tell the operator to confirm (informational only)")
    args = parser.parse_args()
    return run(args.mt5_data_dir, bridge_address=args.bridge_address, whitelist_confirmed=args.whitelist_confirmed)


if __name__ == "__main__":
    raise SystemExit(main())

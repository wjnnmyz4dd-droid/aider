"""Phantom MT5 file installer (Python Deployment Manager).

Locates (or asks for) the active MT5 data folder, copies
PhantomBridgeEA.mq5 into MQL5/Experts/Phantom/ and
PhantomBridgeEA.set into MQL5/Presets/Phantom/, taking a timestamped
backup of any file it would otherwise overwrite. Does NOT compile the
.mq5 -- that step can only happen inside MetaEditor on the real
Windows/MT5 installation; this script prints the exact steps to do it
and does not claim to have done it itself.

Usage: python install_mt5_files.py ["C:\\path\\to\\MT5\\data\\folder"]
  If no path is given, this script tries to auto-detect a single
  MetaQuotes terminal data folder under %APPDATA%\\MetaQuotes\\Terminal\\
  and asks you to confirm/choose if more than one (or none) is found.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SOURCE_DIR = _HERE.parent / "mt5"


def _find_mt5_data_dirs() -> list:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    terminal_root = Path(appdata) / "MetaQuotes" / "Terminal"
    if not terminal_root.exists():
        return []
    return [d for d in terminal_root.iterdir() if d.is_dir() and (d / "MQL5").exists()]


def _resolve_mt5_data_dir(explicit_path: str) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not (path / "MQL5").exists():
            print(f"FAILED: {path}\\MQL5 does not exist -- this does not look like a valid MT5 data folder.", file=sys.stderr)
            raise SystemExit(2)
        return path

    print("No MT5 data folder given -- searching %APPDATA%\\MetaQuotes\\Terminal\\...")
    candidates = _find_mt5_data_dirs()
    if not candidates:
        entered = input("No MT5 terminal data folder was auto-detected. Enter the full path to your MT5 data folder (the one containing MQL5\\): ").strip()
        if not entered:
            print("FAILED: no path given.", file=sys.stderr)
            raise SystemExit(2)
        return _resolve_mt5_data_dir(entered)

    if len(candidates) > 1:
        print("More than one MT5 terminal data folder was found:")
        for candidate in candidates:
            print(f"  {candidate}")
        print("Re-run this script with the correct one as an argument, e.g.:")
        print(f'  python install_mt5_files.py "{candidates[0]}"')
        raise SystemExit(2)

    found = candidates[0]
    print(f"Exactly one MT5 terminal data folder found: {found}")
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


def run(explicit_mt5_dir: str = "") -> int:
    mq5_source = _SOURCE_DIR / "PhantomBridgeEA.mq5"
    set_source = _SOURCE_DIR / "PhantomBridgeEA.set"
    if not mq5_source.exists():
        print(f"FAILED: {mq5_source} not found.", file=sys.stderr)
        return 2
    if not set_source.exists():
        print(f"FAILED: {set_source} not found.", file=sys.stderr)
        return 2

    mt5_data_dir = _resolve_mt5_data_dir(explicit_mt5_dir)

    experts_dir = mt5_data_dir / "MQL5" / "Experts" / "Phantom"
    presets_dir = mt5_data_dir / "MQL5" / "Presets" / "Phantom"
    experts_dir.mkdir(parents=True, exist_ok=True)
    presets_dir.mkdir(parents=True, exist_ok=True)

    mq5_dest = experts_dir / "PhantomBridgeEA.mq5"
    _backup_if_exists(mq5_dest)
    shutil.copy2(mq5_source, mq5_dest)
    print(f"Copied PhantomBridgeEA.mq5 to {experts_dir}")

    set_dest = presets_dir / "PhantomBridgeEA.set"
    _backup_if_exists(set_dest)
    shutil.copy2(set_source, set_dest)
    print(f"Copied PhantomBridgeEA.set to {presets_dir}")

    print()
    print("=" * 60)
    print("Files copied. Compilation is NOT done by this script -- it can")
    print("only happen inside MetaEditor on this real Windows/MT5")
    print("installation. Do this next:")
    print()
    print("  1. Open MetaEditor (from MT5: Tools > MetaQuotes Language Editor,")
    print("     or press F4 inside MT5).")
    print("  2. In MetaEditor's Navigator panel, expand Experts > Phantom")
    print("     and double-click PhantomBridgeEA.mq5 to open it.")
    print("  3. Press F7 (or the Compile toolbar button) to compile.")
    print('  4. Confirm the status/output window shows "0 error(s)" -- a')
    print("     PhantomBridgeEA.ex5 file will appear next to the .mq5 file")
    print(f"     in {experts_dir} only once compilation succeeds.")
    print("  5. Back in MT5, refresh the Navigator panel (right-click >")
    print("     Refresh) so the compiled EA appears under")
    print("     Expert Advisors > Phantom > PhantomBridgeEA.")
    print()
    print("This script has NOT compiled the EA and has NOT verified MT5")
    print("connectivity -- both require the real MetaEditor/MT5 GUI, which")
    print("is outside what a Python script can do.")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Phantom's MT5 EA files")
    parser.add_argument("mt5_data_dir", nargs="?", default="", help="path to the MT5 data folder (auto-detected if omitted)")
    args = parser.parse_args()
    return run(args.mt5_data_dir)


if __name__ == "__main__":
    raise SystemExit(main())

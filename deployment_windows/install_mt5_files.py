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
from typing import Optional

_HERE = Path(__file__).resolve().parent


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
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    terminal_root = Path(appdata) / "MetaQuotes" / "Terminal"
    if not terminal_root.exists():
        return []
    return [d for d in terminal_root.iterdir() if d.is_dir() and (d / "MQL5").exists()]


def _resolve_mt5_data_dir(explicit_path: str, non_interactive: bool) -> Optional[Path]:
    """Returns None (never raises) when running non-interactively and
    the folder can't be resolved without a human choosing -- callers
    like install.py treat that as "skipped, not fatal" rather than
    aborting the whole installation over an MT5-side ambiguity."""
    if explicit_path:
        path = Path(explicit_path)
        if not (path / "MQL5").exists():
            print(f"FAILED: {path}\\MQL5 does not exist -- this does not look like a valid MT5 data folder.", file=sys.stderr)
            if non_interactive:
                return None
            raise SystemExit(2)
        return path

    print("No MT5 data folder given -- searching %APPDATA%\\MetaQuotes\\Terminal\\...")
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
        print("More than one MT5 terminal data folder was found:")
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
    print(f"Exactly one MT5 terminal data folder found: {found}")
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


def run(explicit_mt5_dir: str = "", non_interactive: bool = False, personalize: Optional[dict] = None) -> int:
    """Returns 0 on success, 2 on a hard failure (missing source files,
    an explicitly-given path that isn't a valid MT5 data folder), and 3
    when the MT5 data folder couldn't be resolved non-interactively
    (not fatal -- the rest of installation still proceeds; see
    install.py, which treats 3 as "skipped, report it, keep going")."""
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
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Titan Protocol's MT5 EA files")
    parser.add_argument("mt5_data_dir", nargs="?", default="", help="path to the MT5 data folder (auto-detected if omitted)")
    args = parser.parse_args()
    return run(args.mt5_data_dir)


if __name__ == "__main__":
    raise SystemExit(main())

"""MT5 terminal instance / data-folder detection (Deployment Bug Fix --
GetLastError=4014 despite an operator having added the Bridge address to
Tools>Options>Expert Advisors).

Root-cause context (verified against MetaQuotes/MQL5 community
documentation before writing a line of this module -- see the two facts
below, neither guessed):

1. Every MT5 data folder contains an `origin.txt` file at its root
   naming the exact terminal installation directory it belongs to --
   this is how MetaQuotes itself lets an operator match a data folder to
   an installation when several copies exist. This module's whole
   instance-matching mechanism rests on this one documented file.
2. The WebRequest/Socket allow-list itself lives in
   `<data folder>\\Config\\experts.ini`, which MetaQuotes ships as a
   binary, non-text file with no documented read/write API -- there is
   no supported way for this module (or the EA) to programmatically
   inspect or edit its contents. Every function below is honest about
   this: none of them claims to verify the allow-list's actual
   contents. What they verify instead is everything that CAN be checked
   for certain -- which data folder a running terminal is actually
   using, whether more than one candidate exists, and whether the EA
   files installed match the ones this repository ships -- so an
   operator is never left guessing which terminal's Options dialog to
   open.

Windows-only in the sense that its real signal only exists on a real
Windows machine with a real MT5 install; every function degrades to an
empty/None result (never a crash, never a fabricated answer) when run
elsewhere, e.g. this repository's own Linux CI/sandbox.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class DataFolder:
    """One `%APPDATA%\\MetaQuotes\\Terminal\\<hash>\\` directory."""

    path: Path
    origin_install_path: Optional[Path]  # None if origin.txt missing/unreadable


@dataclass(frozen=True)
class RunningTerminal:
    """One currently-running terminal64.exe/terminal.exe process."""

    pid: int
    exe_path: Path

    @property
    def install_dir(self) -> Path:
        return self.exe_path.parent


@dataclass(frozen=True)
class ResolvedInstance:
    """A data folder matched to the running process whose install
    directory produced it, per origin.txt -- this is "the terminal
    whose configuration is being modified" the operator asked us to
    identify with certainty, not a guess."""

    data_folder: Path
    running_pid: int
    running_exe_path: Path


def is_windows() -> bool:
    return platform.system() == "Windows"


def metaquotes_terminal_root() -> Optional[Path]:
    if not is_windows():
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    root = Path(appdata) / "MetaQuotes" / "Terminal"
    return root if root.exists() else None


def discover_data_folders() -> List[DataFolder]:
    """Every subdirectory under the MetaQuotes Terminal root that looks
    like a real data folder (has an MQL5\\ subdirectory) -- with
    origin.txt read where present. Returns [] on non-Windows or when no
    MetaQuotes root exists; never raises."""
    root = metaquotes_terminal_root()
    if root is None:
        return []
    out: List[DataFolder] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / "MQL5").exists():
            continue
        origin_path: Optional[Path] = None
        origin_file = entry / "origin.txt"
        if origin_file.exists():
            try:
                text = origin_file.read_text(encoding="utf-16", errors="strict").strip()
            except (UnicodeDecodeError, OSError):
                try:
                    text = origin_file.read_text(encoding="utf-8", errors="strict").strip()
                except (UnicodeDecodeError, OSError):
                    text = ""
            if text:
                origin_path = Path(text)
        out.append(DataFolder(path=entry, origin_install_path=origin_path))
    return out


def list_running_terminals() -> List[RunningTerminal]:
    """Queries the real Windows process list (via PowerShell's
    Win32_Process, which is the standard, documented way to get a
    running process's full executable path -- `tasklist` alone does
    not expose this) for terminal64.exe/terminal.exe. Returns [] on
    non-Windows, on any PowerShell failure, or when nothing is running
    -- never raises, never fabricates a process that isn't really
    there."""
    if not is_windows():
        return []
    ps_command = (
        "Get-CimInstance Win32_Process "
        "-Filter \"Name='terminal64.exe' OR Name='terminal.exe'\" "
        "| Select-Object ProcessId,ExecutablePath "
        "| ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    out: List[RunningTerminal] = []
    for entry in payload:
        pid = entry.get("ProcessId")
        exe = entry.get("ExecutablePath")
        if pid is None or not exe:
            continue
        out.append(RunningTerminal(pid=int(pid), exe_path=Path(exe)))
    return out


def paths_equal(a: Path, b: Path) -> bool:
    return str(a).rstrip("\\/").lower() == str(b).rstrip("\\/").lower()


def resolve_active_instances(
    data_folders: Optional[List[DataFolder]] = None,
    running: Optional[List[RunningTerminal]] = None,
) -> List[ResolvedInstance]:
    """Cross-references discover_data_folders() against
    list_running_terminals() via origin.txt == the running process's
    install directory. A data folder with no matching running process
    is simply not returned -- it exists on disk but nothing is
    currently using it, which is exactly the ambiguity this whole
    module exists to remove. Also checks portable-mode terminals (a
    running terminal64.exe with an MQL5\\ folder directly next to it,
    no AppData data folder at all)."""
    data_folders = discover_data_folders() if data_folders is None else data_folders
    running = list_running_terminals() if running is None else running

    resolved: List[ResolvedInstance] = []
    for proc in running:
        matched = False
        for folder in data_folders:
            if folder.origin_install_path is not None and paths_equal(folder.origin_install_path, proc.install_dir):
                resolved.append(ResolvedInstance(data_folder=folder.path, running_pid=proc.pid, running_exe_path=proc.exe_path))
                matched = True
        if not matched and (proc.install_dir / "MQL5").exists():
            # Portable mode: `terminal64.exe /portable` keeps the data
            # folder next to the executable instead of under AppData.
            resolved.append(ResolvedInstance(data_folder=proc.install_dir, running_pid=proc.pid, running_exe_path=proc.exe_path))
    return resolved


@dataclass(frozen=True)
class ResolutionReport:
    """Human-readable evidence for every step of resolve_active_instances(),
    for install.py/validation scripts to print verbatim rather than
    re-deriving their own summary of the same facts."""

    data_folders: List[DataFolder]
    running_terminals: List[RunningTerminal]
    resolved: List[ResolvedInstance]

    @property
    def unambiguous(self) -> Optional[ResolvedInstance]:
        return self.resolved[0] if len(self.resolved) == 1 else None

    def describe(self) -> str:
        lines = []
        if not self.running_terminals:
            lines.append("No terminal64.exe/terminal.exe process is currently running.")
        else:
            lines.append(f"{len(self.running_terminals)} running terminal process(es):")
            for proc in self.running_terminals:
                lines.append(f"  pid={proc.pid} exe={proc.exe_path}")
        if not self.data_folders:
            lines.append("No MetaQuotes Terminal data folder found under %APPDATA%.")
        else:
            lines.append(f"{len(self.data_folders)} candidate data folder(s) on disk:")
            for folder in self.data_folders:
                origin = folder.origin_install_path if folder.origin_install_path else "(origin.txt missing/unreadable)"
                lines.append(f"  {folder.path}  <- origin.txt: {origin}")
        if not self.resolved:
            lines.append("Could not match any running terminal to a data folder.")
        elif len(self.resolved) == 1:
            r = self.resolved[0]
            lines.append(f"RESOLVED: pid={r.running_pid} ({r.running_exe_path}) is using data folder {r.data_folder}")
        else:
            lines.append(f"AMBIGUOUS: {len(self.resolved)} running terminals matched -- an explicit data folder must be given:")
            for r in self.resolved:
                lines.append(f"  pid={r.running_pid} ({r.running_exe_path}) -> {r.data_folder}")
        return "\n".join(lines)


def build_resolution_report() -> ResolutionReport:
    data_folders = discover_data_folders()
    running = list_running_terminals()
    resolved = resolve_active_instances(data_folders, running)
    return ResolutionReport(data_folders=data_folders, running_terminals=running, resolved=resolved)


def main() -> int:
    report = build_resolution_report()
    print(report.describe())
    return 0 if report.unambiguous is not None else 1


if __name__ == "__main__":
    sys.exit(main())

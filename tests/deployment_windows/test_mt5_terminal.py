"""Tests for mt5_terminal.py -- the deployment-bug fix (GetLastError=4014
persisting despite an operator having "added the URL") for detecting
which MT5 terminal instance/data folder is actually running.

Real facts this module rests on (verified against MetaQuotes/MQL5
community documentation before writing it, not guessed -- see its own
module docstring): every MT5 data folder's root contains an origin.txt
naming its install directory, and the allow-list itself lives in a
binary, undocumented experts.ini this module never attempts to read.

This sandbox is Linux with no real MT5 install, so every test either
exercises the honest non-Windows degradation (empty results, never a
crash/fabrication) directly, or mocks platform.system()/subprocess.run
for the Windows-only code paths -- the same pattern already used by
test_process_liveness.py for config_loader.is_process_alive()."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from ._fixtures import DEPLOYMENT_DIR  # ensures deployment_windows/ is on sys.path

import mt5_terminal


class TestNonWindowsDegradesHonestly(unittest.TestCase):
    """This repository's own CI/sandbox is Linux -- every function must
    return an empty/None result here, never raise, never fabricate."""

    def test_is_windows_false_here(self):
        self.assertFalse(mt5_terminal.is_windows())

    def test_metaquotes_terminal_root_is_none(self):
        self.assertIsNone(mt5_terminal.metaquotes_terminal_root())

    def test_discover_data_folders_is_empty(self):
        self.assertEqual(mt5_terminal.discover_data_folders(), [])

    def test_list_running_terminals_is_empty(self):
        self.assertEqual(mt5_terminal.list_running_terminals(), [])

    def test_resolve_active_instances_is_empty(self):
        self.assertEqual(mt5_terminal.resolve_active_instances(), [])

    def test_build_resolution_report_describes_honestly(self):
        report = mt5_terminal.build_resolution_report()
        self.assertIsNone(report.unambiguous)
        text = report.describe()
        self.assertIn("No terminal64.exe/terminal.exe process is currently running", text)
        self.assertIn("No MetaQuotes Terminal data folder found", text)


class TestOriginTxtCrossReference(unittest.TestCase):
    """The real mechanism: a data folder's origin.txt names its install
    directory; a running process's exe path's parent IS that install
    directory. Exercises discover_data_folders()/resolve_active_instances()
    directly against real temp files (origin.txt reading is pure I/O,
    no Windows-only API involved) rather than mocking the file layer."""

    def test_discover_data_folders_reads_origin_txt(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            terminal_root = Path(tmp) / "MetaQuotes" / "Terminal"
            data_folder = terminal_root / "ABCDEF1234567890"
            (data_folder / "MQL5").mkdir(parents=True)
            (data_folder / "origin.txt").write_text(r"C:\Program Files\MetaTrader 5", encoding="utf-8")

            with mock.patch.object(mt5_terminal, "metaquotes_terminal_root", return_value=terminal_root):
                folders = mt5_terminal.discover_data_folders()

            self.assertEqual(len(folders), 1)
            self.assertEqual(folders[0].path, data_folder)
            self.assertEqual(str(folders[0].origin_install_path), r"C:\Program Files\MetaTrader 5")

    def test_data_folder_without_mql5_subfolder_is_not_a_candidate(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            terminal_root = Path(tmp) / "MetaQuotes" / "Terminal"
            not_a_terminal = terminal_root / "Common"
            not_a_terminal.mkdir(parents=True)  # no MQL5\ subfolder -- e.g. the real "Common" folder

            with mock.patch.object(mt5_terminal, "metaquotes_terminal_root", return_value=terminal_root):
                folders = mt5_terminal.discover_data_folders()

            self.assertEqual(folders, [])

    def test_resolve_active_instances_matches_running_process_to_data_folder(self):
        from pathlib import Path

        install_dir = Path(r"C:\Program Files\MetaTrader 5")
        data_folder = mt5_terminal.DataFolder(path=Path(r"C:\Users\op\AppData\Roaming\MetaQuotes\Terminal\ABC"), origin_install_path=install_dir)
        running = mt5_terminal.RunningTerminal(pid=4321, exe_path=install_dir / "terminal64.exe")

        resolved = mt5_terminal.resolve_active_instances(data_folders=[data_folder], running=[running])

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].running_pid, 4321)
        self.assertEqual(resolved[0].data_folder, data_folder.path)

    def test_ambiguous_when_two_running_terminals_both_match(self):
        from pathlib import Path

        install_dir_a = Path(r"C:\MT5_A")
        install_dir_b = Path(r"C:\MT5_B")
        folder_a = mt5_terminal.DataFolder(path=Path(r"C:\Data\A"), origin_install_path=install_dir_a)
        folder_b = mt5_terminal.DataFolder(path=Path(r"C:\Data\B"), origin_install_path=install_dir_b)
        proc_a = mt5_terminal.RunningTerminal(pid=1, exe_path=install_dir_a / "terminal64.exe")
        proc_b = mt5_terminal.RunningTerminal(pid=2, exe_path=install_dir_b / "terminal64.exe")

        resolved = mt5_terminal.resolve_active_instances(data_folders=[folder_a, folder_b], running=[proc_a, proc_b])

        self.assertEqual(len(resolved), 2)
        report = mt5_terminal.ResolutionReport(data_folders=[folder_a, folder_b], running_terminals=[proc_a, proc_b], resolved=resolved)
        self.assertIsNone(report.unambiguous)
        self.assertIn("AMBIGUOUS", report.describe())

    def test_portable_mode_terminal_resolved_without_origin_txt(self):
        """`terminal64.exe /portable` keeps MQL5\\ next to the exe --
        no AppData data folder, no origin.txt, at all."""
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            install_dir = __import__("pathlib").Path(tmp) / "PortableMT5"
            (install_dir / "MQL5").mkdir(parents=True)
            proc = mt5_terminal.RunningTerminal(pid=99, exe_path=install_dir / "terminal64.exe")

            resolved = mt5_terminal.resolve_active_instances(data_folders=[], running=[proc])

            self.assertEqual(len(resolved), 1)
            self.assertEqual(resolved[0].data_folder, install_dir)


class TestListRunningTerminalsWindowsBranch(unittest.TestCase):
    """Mocks platform.system()="Windows" + subprocess.run for the
    PowerShell/Win32_Process call -- the same pattern
    test_process_liveness.py already uses for is_process_alive()'s
    Windows-only tasklist branch."""

    def test_parses_powershell_json_output(self):
        fake_result = subprocess.CompletedProcess(
            args=["powershell"], returncode=0,
            stdout=json.dumps([{"ProcessId": 555, "ExecutablePath": r"C:\MT5\terminal64.exe"}]),
        )
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result) as run_mock:
            result = mt5_terminal.list_running_terminals()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pid, 555)
        self.assertEqual(str(result[0].exe_path), r"C:\MT5\terminal64.exe")
        run_mock.assert_called_once()

    def test_single_object_json_output_not_wrapped_in_a_list(self):
        # ConvertTo-Json emits a bare object, not a list, when exactly
        # one process matches -- must not crash on this shape.
        fake_result = subprocess.CompletedProcess(
            args=["powershell"], returncode=0,
            stdout=json.dumps({"ProcessId": 777, "ExecutablePath": r"C:\MT5\terminal64.exe"}),
        )
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result):
            result = mt5_terminal.list_running_terminals()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pid, 777)

    def test_powershell_failure_returns_empty_not_a_crash(self):
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", side_effect=OSError("powershell not found")):
            self.assertEqual(mt5_terminal.list_running_terminals(), [])

    def test_no_processes_running_returns_empty(self):
        fake_result = subprocess.CompletedProcess(args=["powershell"], returncode=0, stdout="")
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch("subprocess.run", return_value=fake_result):
            self.assertEqual(mt5_terminal.list_running_terminals(), [])


if __name__ == "__main__":
    unittest.main()

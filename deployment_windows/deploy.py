"""Phantom deployment/setup script (Python Deployment Manager).

Verifies Python, creates the local virtual environment, installs
dependencies, verifies folders/configuration/write-access, compiles
the runtime, and runs an import smoke test -- installation only, never
touches engine logic. Fails closed: stops at the first failed
prerequisite and exits non-zero; nothing after a failure runs.

Uses only paths relative to this script's own location (`_HERE`), so
Phantom can be installed and run from any folder.
"""

from __future__ import annotations

import platform
import struct
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    """Locates the installation root -- the folder containing both
    phantom/ and mt5/ -- whether this script lives directly inside it
    (the shipped, flattened C:\\Phantom\\deploy.py layout) or one level
    below it (this repository's own deployment_windows/ subfolder, used
    for development)."""
    for candidate in (here, here.parent):
        if (candidate / "phantom").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Phantom installation root (a folder containing "
        f"both phantom/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


_REPO_ROOT = _find_repo_root(_HERE)
_MIN_PYTHON_VERSION = (3, 9)

_REQUIRED_PHANTOM_PACKAGES = (
    "bridge", "evidence_engine", "market_intelligence", "strategy_engine",
    "risk_engine", "compliance_engine", "runtime", "reliability",
)


class DeploymentError(Exception):
    """Raised by a step to stop deployment immediately -- fail closed,
    never continue past a failed prerequisite."""


def _venv_python() -> Path:
    return _HERE / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / ("python.exe" if platform.system() == "Windows" else "python")


def step_verify_python_version() -> str:
    if sys.version_info < _MIN_PYTHON_VERSION:
        raise DeploymentError(
            f"Python {'.'.join(map(str, _MIN_PYTHON_VERSION))}+ required, "
            f"found {platform.python_version()}. Install a supported version "
            f"from https://www.python.org/downloads/ and ensure it's on PATH."
        )
    is_64bit = struct.calcsize("P") * 8 == 64
    if not is_64bit:
        raise DeploymentError(
            f"64-bit Python is required; found a {struct.calcsize('P') * 8}-bit build. "
            "Install the 64-bit installer."
        )
    return f"Python {platform.python_version()} (64-bit) OK"


def step_create_virtualenv() -> str:
    venv_python = _venv_python()
    if venv_python.exists():
        return f".venv already exists at {venv_python.parent.parent}"
    result = subprocess.run([sys.executable, "-m", "venv", str(_HERE / ".venv")], capture_output=True, text=True)
    if result.returncode != 0:
        raise DeploymentError(f"could not create virtual environment: {result.stderr.strip()}")
    if not venv_python.exists():
        raise DeploymentError(f"venv creation reported success but {venv_python} does not exist")
    return f"Created virtual environment at {_HERE / '.venv'}"


def step_upgrade_pip() -> str:
    venv_python = _venv_python()
    result = subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], capture_output=True, text=True)
    if result.returncode != 0:
        raise DeploymentError(f"pip upgrade failed: {result.stderr.strip()}")
    return "pip upgraded"


def step_install_requirements() -> str:
    venv_python = _venv_python()
    requirements_path = _HERE / "requirements.txt"
    if not requirements_path.exists():
        raise DeploymentError(f"{requirements_path} not found")
    result = subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(requirements_path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise DeploymentError(f"dependency installation failed: {result.stderr.strip()}")
    return "Dependencies installed (Phantom's live runtime is standard-library-only)"


def step_verify_folder_structure() -> str:
    required = [
        _REPO_ROOT / "phantom" / package for package in _REQUIRED_PHANTOM_PACKAGES
    ] + [
        _REPO_ROOT / "mt5" / "PhantomBridgeEA.mq5",
        _REPO_ROOT / "mt5" / "PhantomBridgeEA.set",
        _REPO_ROOT / "config" / "phantom_config.example.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise DeploymentError(
            "required file(s)/folder(s) not found:\n  " + "\n  ".join(missing) +
            "\nExtract the full deployment package so phantom/ and mt5/ sit alongside deployment_windows/."
        )
    return f"All {len(required)} required runtime paths present"


def step_validate_configuration() -> str:
    config_path = _HERE / "phantom_config.json"
    if not config_path.exists():
        raise DeploymentError(
            f"{config_path} not found. Copy config/phantom_config.example.json "
            "to phantom_config.json and edit it before running deploy.py again."
        )
    venv_python = _venv_python()
    check_script = (
        f"import sys; sys.path.insert(0, {str(_REPO_ROOT)!r}); sys.path.insert(0, '.'); "
        "from config_loader import load_settings; from pathlib import Path; "
        f"load_settings(Path({str(config_path)!r}))"
    )
    result = subprocess.run([str(venv_python), "-c", check_script], capture_output=True, text=True, cwd=str(_HERE))
    if result.returncode != 0:
        raise DeploymentError(f"configuration validation failed:\n{result.stderr.strip()}")
    return "Configuration valid"


def step_verify_write_permissions() -> str:
    venv_python = _venv_python()
    config_path = _HERE / "phantom_config.json"
    check_script = (
        f"import sys; sys.path.insert(0, {str(_REPO_ROOT)!r}); sys.path.insert(0, '.'); "
        "from config_loader import load_settings; from pathlib import Path; "
        f"s = load_settings(Path({str(config_path)!r})); "
        "[(p.mkdir(parents=True, exist_ok=True), "
        "(p / '.deploy_write_probe').write_text('ok'), "
        "(p / '.deploy_write_probe').unlink()) for p in (s.log_dir, s.state_dir, s.data_dir)]"
    )
    result = subprocess.run([str(venv_python), "-c", check_script], capture_output=True, text=True, cwd=str(_HERE))
    if result.returncode != 0:
        raise DeploymentError(f"log_dir/state_dir/data_dir are not writable:\n{result.stderr.strip()}")
    return "log_dir/state_dir/data_dir created and writable"


def step_compileall() -> str:
    venv_python = _venv_python()
    result = subprocess.run(
        [str(venv_python), "-m", "compileall", "-q", str(_REPO_ROOT / "phantom"), str(_HERE)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise DeploymentError(f"compileall reported syntax errors:\n{result.stdout.strip()}\n{result.stderr.strip()}")
    return "compileall OK (phantom/ + deployment_windows/)"


def step_import_smoke_test() -> str:
    venv_python = _venv_python()
    imports = "; ".join(f"from phantom.{pkg} import engine as _{pkg}_engine" for pkg in _REQUIRED_PHANTOM_PACKAGES)
    check_script = f"import sys; sys.path.insert(0, {str(_REPO_ROOT)!r}); {imports}; print('ok')"
    result = subprocess.run([str(venv_python), "-c", check_script], capture_output=True, text=True)
    if result.returncode != 0 or "ok" not in result.stdout:
        raise DeploymentError(f"import smoke test failed:\n{result.stderr.strip()}")
    return f"All {len(_REQUIRED_PHANTOM_PACKAGES)} required packages import cleanly"


_STEPS = [
    ("Verify Python version", step_verify_python_version),
    ("Create virtual environment", step_create_virtualenv),
    ("Upgrade pip", step_upgrade_pip),
    ("Install requirements", step_install_requirements),
    ("Verify folder structure", step_verify_folder_structure),
    ("Validate configuration", step_validate_configuration),
    ("Verify write permissions", step_verify_write_permissions),
    ("Run compileall", step_compileall),
    ("Import smoke test", step_import_smoke_test),
]


def main() -> int:
    print("=" * 60)
    print("Phantom Deployment Manager -- deploy.py")
    print("=" * 60)

    results = []
    for index, (label, step_fn) in enumerate(_STEPS, start=1):
        print(f"[{index}/{len(_STEPS)}] {label}...")
        try:
            detail = step_fn()
            print(f"    OK: {detail}")
            results.append((label, True, detail))
        except DeploymentError as exc:
            print(f"    FAILED: {exc}", file=sys.stderr)
            results.append((label, False, str(exc)))
            break  # fail closed -- never continue past a failed prerequisite

    print()
    print("=" * 60)
    print("Deployment Summary")
    print("=" * 60)
    for label, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    remaining = len(_STEPS) - len(results)
    if remaining:
        print(f"  [SKIPPED] {remaining} step(s) not attempted after the failure above")

    if all(ok for _, ok, _ in results) and len(results) == len(_STEPS):
        print()
        print("Deployment completed successfully.")
        print("Next: install_mt5_files.py, then start.py.")
        return 0

    print()
    print("DEPLOYMENT FAILED -- see the FAILED step above. Fix the issue and re-run deploy.py.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

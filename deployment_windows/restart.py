"""Titan Protocol restart script (Python Deployment Manager).

Calls stop.py, confirms shutdown, calls start.py, verifies health.
Contains no logic of its own beyond sequencing those two approved
scripts -- never bypasses either one's own safety checks (this is a
thin sequencer, not a reimplementation).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import stop as stop_module
import start as start_module


def run(config_path: Path) -> int:
    print("=" * 60)
    print("Titan Protocol restart: step 1/3 -- stop")
    print("=" * 60)
    stop_exit = stop_module.run(config_path)
    if stop_exit != 0:
        print("FAILED: stop did not complete cleanly. Refusing to start a new "
              "instance while the old one's state is uncertain. Investigate manually.", file=sys.stderr)
        return 1

    from config_loader import load_settings

    try:
        settings = load_settings(config_path)
    except Exception:  # noqa: BLE001 -- stop already validated config; this is just for the pid check below
        settings = None
    if settings is not None and (settings.state_dir / "titan_protocol.pid").exists():
        print("FAILED: titan_protocol.pid still exists after stop reported success. Refusing to start a new instance.", file=sys.stderr)
        return 1
    print("Shutdown confirmed.")

    print("=" * 60)
    print("Titan Protocol restart: step 2/3 -- start")
    print("=" * 60)
    start_exit = start_module.launch_and_report(config_path)

    print("=" * 60)
    print("Titan Protocol restart: step 3/3 -- health verification")
    print("=" * 60)
    print("start.py's own health check already ran above; its exit code is this script's exit code.")
    return start_exit


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart the Titan Protocol deployment")
    parser.add_argument("--config", default=str(_HERE / "titan_protocol_config.json"))
    args = parser.parse_args()
    return run(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())

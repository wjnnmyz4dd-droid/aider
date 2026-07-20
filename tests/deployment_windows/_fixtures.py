"""Shared test-only fixtures for deployment_windows tests -- puts
deployment_windows/ on sys.path (it is a flat script directory, not a
package) and provides a real, temp-file-backed config to load
`config_loader.load_settings()` against."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_DIR = REPO_ROOT / "deployment_windows"
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

EXAMPLE_CONFIG_PATH = DEPLOYMENT_DIR / "config" / "titan_protocol_config.example.json"
TEST_API_KEY_ENV_VAR = "TITAN_PROTOCOL_TEST_BRIDGE_API_KEY"


def load_example_config() -> Dict[str, Any]:
    return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))


def write_config(
    tmp_path: Path, overrides: Optional[Dict[str, Any]] = None,
    compliance_overrides: Optional[Dict[str, Any]] = None,
) -> Path:
    """Writes a real config file (based on the shipped example) with
    `overrides` deep-merged into `bridge` and `compliance_overrides`
    deep-merged into `compliance` (the only two sections these tests
    vary), and points `bridge.api_key_env_var` at a real, always-set
    test environment variable so `load_settings()` never fails for an
    unrelated secret-resolution reason."""
    config = load_example_config()
    os.environ[TEST_API_KEY_ENV_VAR] = "test-key-value"
    config["bridge"]["api_key_env_var"] = TEST_API_KEY_ENV_VAR
    if overrides:
        config["bridge"].update(overrides)
    if compliance_overrides:
        config["compliance"].update(compliance_overrides)
    path = tmp_path / "titan_protocol_config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path

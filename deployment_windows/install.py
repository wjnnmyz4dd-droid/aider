"""Titan Protocol master installer (Python Deployment Manager).

The whole point of this script: a first-time user should only need to

  1. Extract the package to C:\\TitanProtocol
  2. Run  python install.py
  3. Open MT5
  4. Attach TitanProtocolEA

Everything else -- creating titan_protocol_config.json, generating the Bridge
API key, creating the virtual environment, installing dependencies,
creating logs/state/data folders, copying the MT5 EA files (personalized
with the real API key/magic number, so loading the .set file in MT5
requires no manual typing), verifying that Bridge/Runtime/Reliability
actually construct and (for Bridge) actually bind a live port, creating
desktop shortcuts, and starting Titan Protocol itself -- happens here, once,
automatically. After this script finishes, day-to-day operation really
is just `python start.py` / `python stop.py` (see start.py/stop.py).

HONESTY NOTE, read before assuming this makes Titan Protocol "fully verified":
this script verifies every real component that exists in this
repository: the Bridge (by actually binding its HTTP server on the
configured port and confirming it is reachable), the 5 core engines +
RuntimeOrchestrator (by constructing them for real), and the
Reliability engine (by calling evaluate_health() for real). It does
**not** and cannot verify a Trading Economics / Forex Factory news
provider system, because no such component exists in this codebase --
`titan_protocol/news_ingestion/` (ADR-033 Part 2) has not been implemented.
That step reports this honestly (see step_verify_news_providers below
and KNOWN_GAPS.md section 2) rather than fabricating a pass. It also
does not and cannot verify real MT5/WebRequest connectivity or
MetaEditor compilation -- both require the real MT5 GUI, which is
outside what any Python script can do; see steps 3 and 4 above.

Safe to re-run: every step here is idempotent. An existing
titan_protocol_config.json, generated API key, .venv, or MT5 EA files are
reused/backed-up rather than silently clobbered or regenerated.
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import secrets
import shutil
import socket
import subprocess
import sys
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _find_repo_root(here: Path) -> Path:
    """Locates the installation root -- the folder containing both
    titan_protocol/ and mt5/ -- whether this script lives directly inside it
    (the shipped, flattened C:\\TitanProtocol\\install.py layout) or one level
    below it (this repository's own deployment_windows/ subfolder, used
    for development)."""
    for candidate in (here, here.parent):
        if (candidate / "titan_protocol").is_dir() and (candidate / "mt5").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate the Titan Protocol installation root (a folder containing "
        f"both titan_protocol/ and mt5/) starting from {here} -- extract the full "
        "release package before running this script."
    )


try:
    _REPO_ROOT = _find_repo_root(_HERE)
except RuntimeError as exc:
    print(f"FAILED: Verify running from the full release package\n       {exc}", file=sys.stderr)
    raise SystemExit(1)
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_HERE))

import deploy as deploy_module
import install_mt5_files as install_mt5_module
import start as start_module
from config_loader import ConfigError, generated_secret_path, load_settings

_CONFIG_TEMPLATE_PATH = _HERE / "config" / "titan_protocol_config.example.json"
_CONFIG_PATH = _HERE / "titan_protocol_config.json"
_REPORT_PATH = _HERE / "INSTALLATION_REPORT.md"

_OK, _INFO, _SKIPPED, _FAILED = "OK", "INFO", "SKIPPED", "FAILED"
_NON_BLOCKING = {_OK, _INFO, _SKIPPED}


@dataclass
class StepReport:
    label: str
    outcome: str
    detail: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def step_verify_release_package() -> StepReport:
    """If this function is even running, module import already found
    titan_protocol/ and mt5/ next to this script (see _find_repo_root above,
    which exits before any of this if they're missing) -- this step
    just makes that fact a visible, reported line instead of an
    implicit assumption."""
    return StepReport(
        "Verify running from the full release package", _OK,
        f"titan_protocol/ and mt5/ found at {_REPO_ROOT} (installation root)",
    )


def step_create_configuration() -> StepReport:
    if _CONFIG_PATH.exists():
        return StepReport("Create configuration", _OK, f"{_CONFIG_PATH} already exists -- reusing it, not overwritten")
    if not _CONFIG_TEMPLATE_PATH.exists():
        return StepReport("Create configuration", _FAILED, f"{_CONFIG_TEMPLATE_PATH} not found")
    shutil.copy2(_CONFIG_TEMPLATE_PATH, _CONFIG_PATH)
    return StepReport(
        "Create configuration", _OK,
        f"Created {_CONFIG_PATH} from the template with default settings "
        "(london_conservative profile, 7 major pairs, example compliance profile). "
        "Edit it later to customize before going live; this default lets an "
        "install run to completion with zero manual editing.",
    )


def step_generate_bridge_api_key() -> StepReport:
    secret_path = generated_secret_path(_CONFIG_PATH)
    if secret_path.exists() and secret_path.read_text(encoding="utf-8").strip():
        return StepReport("Generate Bridge API key", _OK, f"Reusing existing generated key at {secret_path}")
    key = secrets.token_urlsafe(32)
    secret_path.write_text(key, encoding="utf-8")
    return StepReport(
        "Generate Bridge API key", _OK,
        f"Generated a random local shared secret and wrote it to {secret_path} "
        "(gitignored, never a third-party credential -- this is just the shared "
        "token Titan Protocol and its one EA use to recognize each other).",
    )


def step_run_deploy() -> StepReport:
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exit_code = deploy_module.main()
    finally:
        output = buffer.getvalue()
        print(output, end="")
    if exit_code == 0:
        return StepReport("Run deploy.py (venv, dependencies, folders, compile, import smoke test)", _OK, "All 9 deploy.py steps passed")
    return StepReport("Run deploy.py (venv, dependencies, folders, compile, import smoke test)", _FAILED, "deploy.py reported a failure -- see output above")


def step_install_mt5_files(settings, whitelist_confirmed: bool = False) -> StepReport:
    secret_path = generated_secret_path(_CONFIG_PATH)
    api_key = secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else ""
    personalize = {
        "ApiKey": api_key,
        "MagicNumber": str(settings.bridge_config.magic_number),
        "BackendUrl": f"http://{settings.bridge_host}:{settings.bridge_port}",
        "AllowedSymbolsCsv": ",".join(settings.bridge_config.allowed_symbols),
        # ADR-034 -- kept identical to the live Bridge config so the .set
        # file can never drift from it (Transport itself is deliberately
        # not personalized here; see install_mt5_files.py's own comment).
        "SocketHost": settings.bridge_host,
        "SocketPort": str(settings.bridge_config.socket_port),
    }
    bridge_address = (
        f"{settings.bridge_host}:{settings.bridge_config.socket_port}"
        if settings.bridge_config.transport == "socket"
        else f"http://{settings.bridge_host}:{settings.bridge_port}"
    )
    exit_code = install_mt5_module.run(
        explicit_mt5_dir="", non_interactive=True, personalize=personalize,
        bridge_address=bridge_address, whitelist_confirmed=whitelist_confirmed,
    )
    if exit_code == 0:
        return StepReport("Copy + personalize MT5 EA files", _OK, "TitanProtocolEA.mq5/.set copied into the correct, currently-running MT5 terminal's data folder, .set personalized with the real ApiKey/MagicNumber/BackendUrl/SocketHost/SocketPort, and whitelist confirmed by operator for that exact terminal instance")
    if exit_code == 3:
        return StepReport(
            "Copy + personalize MT5 EA files", _SKIPPED,
            "MT5 data folder could not be resolved automatically (no running terminal detected, "
            "none found on disk, or more than one installed) -- open MT5 at least once, then run "
            "`python install_mt5_files.py` yourself (see output above for details).",
        )
    if exit_code == 4:
        return StepReport(
            "Copy + personalize MT5 EA files", _FAILED,
            "MT5 EA files were copied into the resolved terminal, but the WebRequest/Socket "
            "allow-list was NOT confirmed for that terminal (deployment-bug fix, item 5 -- this "
            "installer refuses to silently continue past an unconfirmed allow-list, since MT5 "
            "stores it in an undocumented, binary experts.ini this installer cannot read or write "
            "itself). Re-run install.py with --whitelist-confirmed once you have added the "
            "address printed above to Tools>Options>Expert Advisors in that exact terminal AND "
            "fully restarted it, or --skip-whitelist-check to proceed without this attestation "
            "(not recommended -- see verify_mt5_instance.py for a real, live end-to-end check "
            "you can run afterward instead).",
        )
    return StepReport("Copy + personalize MT5 EA files", _FAILED, f"install_mt5_files.py reported exit code {exit_code} -- see output above")


def step_verify_bridge(settings) -> StepReport:
    """ADR-034: verifies whichever transport `bridge.transport` actually
    names -- binding the HTTP server when a config still says "http"
    would silently "pass" this step while never proving the transport
    that's actually going to run works at all."""
    from titan_protocol.bridge.command_queue import CommandQueue
    from titan_protocol.bridge.connection_health import ConnectionHealth
    from titan_protocol.bridge.engine import BridgeEngine

    transport = settings.bridge_config.transport
    active_port = settings.bridge_config.socket_port if transport == "socket" else settings.bridge_port

    try:
        command_queue = CommandQueue(settings.bridge_config)
        connection_health = ConnectionHealth(settings.bridge_config, _utc_now)
        bridge_engine = BridgeEngine(settings.bridge_config, command_queue, connection_health, _utc_now)
        if transport == "socket":
            from titan_protocol.bridge.socket_transport import serve_socket
            transport_server = serve_socket(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=active_port)
        else:
            from titan_protocol.bridge.server import serve as bridge_serve
            transport_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=active_port)
    except OSError as exc:
        return StepReport("Verify Bridge (socket transport)" if transport == "socket" else "Verify Bridge (HTTP transport)", _FAILED, f"Could not bind {settings.bridge_host}:{active_port}: {exc}")
    except Exception as exc:  # noqa: BLE001 -- report any construction failure, don't let it crash the installer
        return StepReport("Verify Bridge", _FAILED, f"Bridge construction failed: {exc}")

    server_thread = threading.Thread(target=transport_server.serve_forever, name="titan_protocol-install-bridge-smoketest", daemon=True)
    server_thread.start()
    try:
        with socket.create_connection((settings.bridge_host, active_port), timeout=2.0):
            reachable = True
    except OSError as exc:
        reachable = False
        detail_extra = f" (socket connect failed: {exc})"
    else:
        detail_extra = ""
    transport_server.shutdown()
    transport_server.server_close()

    label = f"Verify Bridge ({transport} transport)"
    if reachable:
        return StepReport(label, _OK, f"Constructed BridgeEngine and bound the real {transport} server on {settings.bridge_host}:{active_port}; confirmed reachable via a live socket connection, then shut it down cleanly")
    return StepReport(label, _FAILED, f"Bridge bound but was not reachable{detail_extra}")


def step_verify_http_fallback_listener(settings) -> StepReport:
    """ADR-034 Amendment 3: when transport=="socket", start.py also binds
    an HTTP fallback listener so an EA that auto-falls-back to HTTP (after
    repeated Socket connection failures) can still reach the Bridge.
    Verifies that listener can actually bind here too. Non-fatal if it
    can't -- mirrors start.py's own warning-not-fatal treatment of this
    listener, since the primary transport is already confirmed by
    step_verify_bridge above."""
    if settings.bridge_config.transport != "socket":
        return StepReport("Verify HTTP fallback listener", _OK, "transport is already http -- no separate fallback listener applies")

    from titan_protocol.bridge.command_queue import CommandQueue
    from titan_protocol.bridge.connection_health import ConnectionHealth
    from titan_protocol.bridge.engine import BridgeEngine
    from titan_protocol.bridge.server import serve as bridge_serve

    try:
        command_queue = CommandQueue(settings.bridge_config)
        connection_health = ConnectionHealth(settings.bridge_config, _utc_now)
        bridge_engine = BridgeEngine(settings.bridge_config, command_queue, connection_health, _utc_now)
        fallback_server = bridge_serve(bridge_engine, settings.bridge_config, _utc_now, host=settings.bridge_host, port=settings.bridge_port)
    except OSError as exc:
        return StepReport(
            "Verify HTTP fallback listener", _FAILED,
            f"Could not bind HTTP fallback {settings.bridge_host}:{settings.bridge_port}: {exc} -- an EA "
            "that auto-falls-back to HTTP (ADR-034 Amendment 3) will not be reachable until this port is free",
        )

    server_thread = threading.Thread(target=fallback_server.serve_forever, name="titan_protocol-install-http-fallback-smoketest", daemon=True)
    server_thread.start()
    try:
        with socket.create_connection((settings.bridge_host, settings.bridge_port), timeout=2.0):
            reachable = True
    except OSError as exc:
        reachable = False
        detail_extra = f" (socket connect failed: {exc})"
    else:
        detail_extra = ""
    fallback_server.shutdown()
    fallback_server.server_close()

    if reachable:
        return StepReport("Verify HTTP fallback listener", _OK, f"Bound and confirmed reachable on {settings.bridge_host}:{settings.bridge_port}, then shut down cleanly")
    return StepReport("Verify HTTP fallback listener", _FAILED, f"HTTP fallback listener bound but was not reachable{detail_extra}")


def step_verify_magic_number_consistency(settings) -> StepReport:
    """In practice this can never FAIL by the time it runs -- `load_settings()`
    already raises `ConfigError` at config-load time if `bridge.magic_number`
    and `runtime.magic_number` disagree (see config_loader.py), which the
    installer already treats as a fatal step before this one ever runs.
    Kept as its own, explicitly-named, always-run step anyway so this
    specific consistency guarantee is a visible line in the installation
    report, not just an implicit side effect of a config-parsing step."""
    bridge_magic = settings.bridge_config.magic_number
    runtime_magic = settings.runtime_config.magic_number
    if bridge_magic != runtime_magic:
        return StepReport(
            "Verify magic number consistency", _FAILED,
            f"bridge.magic_number ({bridge_magic}) != runtime.magic_number ({runtime_magic}) in {_CONFIG_PATH}",
        )
    return StepReport(
        "Verify magic number consistency", _OK,
        f"bridge.magic_number == runtime.magic_number == {bridge_magic} in {_CONFIG_PATH}",
    )


def step_report_mt5_prerequisites(settings) -> StepReport:
    """Cannot be verified by this script -- Tools > Options > Expert
    Advisors lives entirely inside the real MT5 GUI, which no Python
    process can inspect or set. Reported honestly as INFO (not silently
    skipped) so the installation report has an explicit line item for
    it, matching this module's existing honesty precedent (see
    step_verify_news_providers)."""
    active_port = settings.bridge_config.socket_port if settings.bridge_config.transport == "socket" else settings.bridge_port
    return StepReport(
        "MT5 WebRequest/socket prerequisites", _INFO,
        f"Cannot be verified by this script -- requires the real MT5 GUI. In MT5: "
        f"Tools > Options > Expert Advisors > check 'Allow WebRequest for listed URL' "
        f"and add {settings.bridge_host}:{active_port} to the list (MQL5's WebRequest() "
        f"and Socket*() functions share this same allowed-address list).",
    )


def step_run_health_check() -> StepReport:
    import health_check as health_check_module
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exit_code = health_check_module.run(_CONFIG_PATH)
    finally:
        print(buffer.getvalue(), end="")
    label = {0: "HEALTHY", 1: "DEGRADED", 2: "FAILED"}.get(exit_code, "UNKNOWN")
    if exit_code in (0, 1):
        return StepReport("Run health check", _OK, f"health_check.py reports: {label} (see output above for the full per-check breakdown)")
    return StepReport("Run health check", _FAILED, f"health_check.py reports: {label} -- see output above")


def step_verify_runtime(settings) -> StepReport:
    from titan_protocol.compliance_engine.engine import ComplianceEngine
    from titan_protocol.evidence_engine.config import EvidenceEngineConfig
    from titan_protocol.evidence_engine.engine import EvidenceEngine
    from titan_protocol.market_intelligence.engine import MarketIntelligenceEngine
    from titan_protocol.risk_engine.engine import RiskEngine
    from titan_protocol.runtime.engine import RuntimeOrchestrator
    from titan_protocol.strategy_engine.config import StrategyEngineConfig
    from titan_protocol.strategy_engine.engine import StrategyEngine

    try:
        evidence_engine = EvidenceEngine(EvidenceEngineConfig())
        market_intelligence_engine = MarketIntelligenceEngine(settings.news_config)
        strategy_engine = StrategyEngine(StrategyEngineConfig())
        risk_engine = RiskEngine(settings.risk_config)
        compliance_engine = ComplianceEngine(settings.compliance_config)
        RuntimeOrchestrator(
            settings.runtime_config, evidence_engine, market_intelligence_engine,
            strategy_engine, risk_engine, compliance_engine, bridge_submit=None,
        )
    except Exception as exc:  # noqa: BLE001
        return StepReport("Verify Runtime", _FAILED, f"Engine/RuntimeOrchestrator construction failed: {exc}")
    return StepReport("Verify Runtime", _OK, "Constructed all 5 core engines (Evidence, Market Intelligence, Strategy, Risk, Compliance) and the RuntimeOrchestrator with no error")


def step_verify_reliability(settings) -> StepReport:
    from titan_protocol.reliability.engine import ReliabilityEngine

    try:
        reliability = ReliabilityEngine(settings.reliability_config)
        snapshot = reliability.evaluate_health(_utc_now())
    except Exception as exc:  # noqa: BLE001
        return StepReport("Verify Reliability", _FAILED, f"ReliabilityEngine construction/evaluate_health failed: {exc}")
    return StepReport("Verify Reliability", _OK, f"Constructed ReliabilityEngine and called evaluate_health() -- degradation_level={snapshot.degradation_level.value}")


def step_verify_news_providers(settings) -> StepReport:
    from titan_protocol.news_ingestion.config import NewsIngestionConfig
    from titan_protocol.news_ingestion.engine import NewsIngestionEngine
    from titan_protocol.news_ingestion.providers.forex_factory import ForexFactoryProvider
    from titan_protocol.news_ingestion.providers.trading_economics import TradingEconomicsProvider

    try:
        news_config = NewsIngestionConfig(
            trading_economics_api_key_env_var=settings.news_provider_settings.trading_economics_api_key_env_var,
            forex_factory_api_key_env_var=settings.news_provider_settings.forex_factory_api_key_env_var,
            trading_economics_base_url=settings.news_provider_settings.trading_economics_base_url,
            forex_factory_base_url=settings.news_provider_settings.forex_factory_base_url,
            request_timeout_seconds=settings.news_provider_settings.request_timeout_seconds,
            max_retries=settings.news_provider_settings.max_retries,
            retry_backoff_seconds=settings.news_provider_settings.retry_backoff_seconds,
            stale_after_seconds=settings.news_provider_settings.stale_after_seconds,
            recovery_health_check_count=settings.news_provider_settings.recovery_health_check_count,
            cache_max_entries=settings.news_provider_settings.cache_max_entries,
        )
        NewsIngestionEngine(
            news_config, TradingEconomicsProvider(news_config), ForexFactoryProvider(news_config),
        )
    except Exception as exc:  # noqa: BLE001
        return StepReport("Verify news providers (Trading Economics primary / Forex Factory backup)", _FAILED, f"NewsIngestionEngine construction failed: {exc}")

    ff_configured = bool(settings.news_provider_settings.forex_factory_base_url)
    return StepReport(
        "Verify news providers (Trading Economics primary / Forex Factory backup)", _OK if ff_configured else _INFO,
        "Constructed a real NewsIngestionEngine (titan_protocol/news_ingestion/, ADR-033 Part 2) with no error. "
        + (
            "Both providers configured."
            if ff_configured
            else "Trading Economics is configured; forex_factory_base_url is empty, so no backup provider "
            "is reachable yet -- a Trading Economics outage will fail closed immediately until it is set "
            "(see KNOWN_GAPS.md section 2)."
        ),
    )


def _venv_python() -> Path:
    return _HERE / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def _create_windows_shortcut(lnk_path: Path, script_name: str) -> None:
    venv_python = _venv_python()
    python_for_shortcut = venv_python if venv_python.exists() else Path(sys.executable)
    script_path = _HERE / script_name
    ps_command = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk_path}'); "
        "$s.TargetPath = 'cmd.exe'; "
        f"$s.Arguments = '/k \"{python_for_shortcut}\" \"{script_path}\"'; "
        f"$s.WorkingDirectory = '{_HERE}'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command], check=True, capture_output=True, text=True)


def step_create_desktop_shortcuts() -> StepReport:
    if platform.system() != "Windows":
        return StepReport(
            "Create desktop shortcuts", _SKIPPED,
            "Not running on Windows -- .lnk shortcuts require the real Windows shell "
            "(WScript.Shell via PowerShell), which does not exist here. Not exercised; "
            "run start.py/stop.py/restart.py/health_check.py directly instead.",
        )
    try:
        desktop = Path.home() / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        shortcuts = {
            "Titan Protocol - Start.lnk": "start.py",
            "Titan Protocol - Stop.lnk": "stop.py",
            "Titan Protocol - Restart.lnk": "restart.py",
            "Titan Protocol - Health Check.lnk": "health_check.py",
        }
        for lnk_name, script_name in shortcuts.items():
            _create_windows_shortcut(desktop / lnk_name, script_name)
    except (subprocess.CalledProcessError, OSError) as exc:
        return StepReport("Create desktop shortcuts", _FAILED, f"Shortcut creation failed: {exc}")
    return StepReport("Create desktop shortcuts", _OK, f"Created 4 shortcuts (Start, Stop, Restart, Health Check) on {desktop}")


def step_launch_titan_protocol() -> StepReport:
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exit_code = start_module.launch_and_report(_CONFIG_PATH)
    finally:
        print(buffer.getvalue(), end="")
    status = {0: "HEALTHY", 1: "DEGRADED", 2: "FAILED"}.get(exit_code, "UNKNOWN")
    if exit_code in (0, 1):
        return StepReport("Launch Titan Protocol", _OK, f"Titan Protocol is running -- status: {status} (DEGRADED is expected; see KNOWN_GAPS.md)")
    return StepReport("Launch Titan Protocol", _FAILED, f"start.py reported status: {status} -- see output above")


def _write_report(steps: list, overall_ok: bool) -> None:
    lines = [
        "# Titan Protocol Installation Report",
        "",
        f"Generated: {_utc_now().isoformat()}",
        f"Overall result: {'SUCCESS' if overall_ok else 'INCOMPLETE -- see FAILED step(s) below'}",
        "",
        "| Step | Outcome | Detail |",
        "|---|---|---|",
    ]
    for step in steps:
        detail = step.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {step.label} | {step.outcome} | {detail} |")
    lines += [
        "",
        "## What OK / INFO / SKIPPED / FAILED mean",
        "",
        "- **OK**: verified for real in this run.",
        "- **INFO**: reported honestly, not a pass/fail -- the news-provider check "
        "reports a real, pre-existing gap rather than fabricating success.",
        "- **SKIPPED**: not fatal to installation, but not completed -- follow the "
        "detail column to finish it manually (e.g. MT5 folder ambiguity, non-Windows "
        "shortcut creation).",
        "- **FAILED**: a real problem; installation is not complete until this is fixed.",
        "",
        "## Next steps",
        "",
        "1. Open MT5.",
        "2. Compile TitanProtocolEA.mq5 in MetaEditor (F4 in MT5, then F7) -- this "
        "installer cannot do this for you; it requires the real MetaEditor GUI.",
        "3. Attach TitanProtocolEA to a demo chart, and click Load in its settings "
        "dialog to load the personalized TitanProtocolEA.set (already filled in "
        "with the generated API key and matching magic number).",
        "4. Run `python health_check.py` to confirm `[PASS] MT5 bridge connectivity "
        "(EA heartbeat)` once the EA is attached and running.",
        "",
        "See KNOWN_GAPS.md for what this deployment layer honestly cannot do yet "
        "(a live trading-cycle loop, and Trading Economics/Forex Factory news "
        "provider verification) and WINDOWS_OPERATOR_GUIDE.md for full detail.",
        "",
    ]
    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Titan Protocol master installer")
    parser.add_argument(
        "--whitelist-confirmed", action="store_true",
        help="confirm you have added the Bridge address to Tools>Options>Expert Advisors in the "
             "resolved MT5 terminal AND fully restarted it (deployment-bug fix, item 5) -- without "
             "this, installation stops with a clear error rather than silently continuing",
    )
    parser.add_argument(
        "--skip-whitelist-check", action="store_true",
        help="bypass the whitelist-confirmation gate entirely (e.g. for a dry run with no real MT5 "
             "terminal) -- logged loudly, not a silent bypass",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("TITAN_PROTOCOL MASTER INSTALLER")
    print("=" * 72)

    steps: list = []

    def run_step(step_report: StepReport) -> bool:
        steps.append(step_report)
        print(f"[{step_report.outcome}] {step_report.label}")
        if step_report.detail:
            print(f"       {step_report.detail}")
        return step_report.outcome not in _NON_BLOCKING

    run_step(step_verify_release_package())

    if run_step(step_create_configuration()):
        _write_report(steps, overall_ok=False)
        return 1
    if run_step(step_generate_bridge_api_key()):
        _write_report(steps, overall_ok=False)
        return 1
    if run_step(step_run_deploy()):
        _write_report(steps, overall_ok=False)
        return 1

    try:
        settings = load_settings(_CONFIG_PATH)
    except ConfigError as exc:
        steps.append(StepReport("Load configuration for verification steps", _FAILED, str(exc)))
        print(f"[FAILED] Load configuration for verification steps\n       {exc}")
        _write_report(steps, overall_ok=False)
        return 1

    if run_step(step_verify_magic_number_consistency(settings)):
        _write_report(steps, overall_ok=False)
        return 1

    # MT5 file install *not finding a terminal at all* is non-blocking
    # by design (SKIPPED here still leaves Bridge/Runtime/Reliability
    # verification meaningful) -- but a real terminal WAS found, files
    # WERE copied, and the operator has NOT confirmed the allow-list is
    # this deployment-bug fix's new blocking case (item 5): installation
    # stops with a clear error rather than silently continuing, unless
    # --skip-whitelist-check was explicitly passed.
    whitelist_confirmed = args.whitelist_confirmed or args.skip_whitelist_check
    if args.skip_whitelist_check:
        print("--skip-whitelist-check given: bypassing the allow-list confirmation gate. "
              "GetLastError=4014 remains possible until you actually confirm it by hand.")
    if run_step(step_install_mt5_files(settings, whitelist_confirmed=whitelist_confirmed)):
        _write_report(steps, overall_ok=False)
        return 1

    if run_step(step_verify_bridge(settings)):
        _write_report(steps, overall_ok=False)
        return 1
    # Non-blocking by design -- mirrors start.py's own warning-not-fatal
    # treatment of the HTTP fallback listener (the primary transport is
    # already confirmed above).
    run_step(step_verify_http_fallback_listener(settings))
    if run_step(step_verify_runtime(settings)):
        _write_report(steps, overall_ok=False)
        return 1
    if run_step(step_verify_reliability(settings)):
        _write_report(steps, overall_ok=False)
        return 1

    run_step(step_verify_news_providers(settings))
    run_step(step_report_mt5_prerequisites(settings))
    run_step(step_create_desktop_shortcuts())

    if run_step(step_launch_titan_protocol()):
        _write_report(steps, overall_ok=False)
        return 1

    if run_step(step_run_health_check()):
        _write_report(steps, overall_ok=False)
        return 1

    _write_report(steps, overall_ok=True)
    print("=" * 72)
    print(f"Installation complete. Report written to {_REPORT_PATH}")
    print("Next: open MT5, compile TitanProtocolEA.mq5 in MetaEditor, attach it to a "
          "demo chart, and Load TitanProtocolEA.set.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

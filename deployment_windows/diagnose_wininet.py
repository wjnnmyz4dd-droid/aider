"""WinINet-layer diagnostic for the Bridge's HTTP transport -- proves,
with real measured evidence, whether this machine's WinINet configuration
is adding the multi-second delay-then-pseudo-status failure signature
(`pseudoStatus=1001`/`GetLastError=5203`, elapsed exceeding WebRequest()'s
own timeout) that this exact deployment's Experts log has shown, instead
of guessing at a cause.

Why this is the leading hypothesis, stated plainly: MQL5's `WebRequest()`
goes through Windows' WinINet stack using `INTERNET_OPEN_TYPE_PRECONFIG`
(the same mode Internet Explorer/system "Internet Options" settings
govern) -- this applies to EVERY request WinINet makes, including a
request to `127.0.0.1` (this EA's `BackendUrl` is always the literal
loopback IP, never a hostname, so DNS/IPv6-fallback is not a factor
here). If "Automatically detect settings" (WPAD) is enabled, or a proxy
server is configured without an explicit bypass for local addresses,
WinINet will still attempt proxy resolution for a loopback request --
a well-documented, common cause of exactly this multi-second hang before
either succeeding or failing with a pseudo-status. This is standard,
widely-documented Windows networking behavior, not a guess about
undocumented MT5 internals (contrast with the native-socket allow-list
investigation, where this session could NOT establish MT5's exact
`Socket*()` whitelist format with confidence -- see ADR-034 Amendment 3).

What this script actually measures (never merely asserted in prose):
  1. The real registry state of this Windows user's proxy configuration
     (`ProxyEnable`, `ProxyServer`, `ProxyOverride`, `AutoConfigURL`) --
     context only, not the verdict by itself.
  2. A real, timed HTTP round-trip to the actual running Bridge, once
     honoring this machine's system proxy configuration (mirrors what
     WinINet does for MQL5's `WebRequest()`) and once with the proxy
     explicitly bypassed -- the *difference* between these two timings
     is direct, measured evidence of proxy-resolution overhead on this
     exact machine, for this exact destination, right now.
  3. What this script CANNOT measure and says so explicitly: if
     `AutoConfigURL` names a PAC (proxy auto-config) script, Python's
     `urllib` does not execute that script the way WinINet does, so a
     PAC-driven delay may not show up in check 2 even when it is the
     real cause. Check 1 flags this directly so it is never silently
     missed.

Usage: python diagnose_wininet.py [path/to/titan_protocol_config.json] [--fix]
  --fix   Only after the diagnosis above shows the local Bridge address
          is NOT in the proxy bypass list: adds the minimal, targeted
          bypass entry ("<local>;127.0.0.1") to ProxyOverride so loopback
          traffic skips proxy resolution -- deliberately never disables
          ProxyEnable/ProxyServer themselves, since a real proxy may
          still be required for this deployment's own external calls
          (Trading Economics/Forex Factory news providers). Re-runs the
          timing test afterward to prove the fix actually changed
          anything, rather than just claiming it did.

Exit code: 0 if the Bridge was reachable and no proxy-related red flag
was found; 1 if a red flag was found (still not fatal to Titan Protocol
itself -- this is a Windows-networking diagnostic, not a Bridge health
check); 2 on a configuration/environment error (e.g. Bridge not running).
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
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

from config_loader import ConfigError, load_settings  # noqa: E402

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _print_result(ok, label: str, detail: str) -> None:
    tag = "PASS" if ok is True else ("INFO" if ok is None else "FAIL")
    print(f"[{tag}] {label}")
    if detail:
        print(f"       {detail}")


def read_proxy_registry():
    """Real registry values only -- never inferred. Returns None (with
    an explicit printed reason) on any non-Windows platform or read
    failure, rather than fabricating a value."""
    try:
        import winreg
    except ImportError:
        _print_result(None, "Proxy registry state", "Not running on Windows -- winreg module unavailable (expected in this repo's own Linux sandbox).")
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH)
    except OSError as exc:
        _print_result(None, "Proxy registry state", f"Could not open registry key {_REG_PATH}: {exc}")
        return None

    def _read(name, default=None):
        try:
            value, _ = winreg.QueryValueEx(key, name)
            return value
        except FileNotFoundError:
            return default

    values = {
        "ProxyEnable": _read("ProxyEnable", 0),
        "ProxyServer": _read("ProxyServer", ""),
        "ProxyOverride": _read("ProxyOverride", ""),
        "AutoConfigURL": _read("AutoConfigURL", ""),
    }
    key.Close()

    _print_result(True, "Proxy registry state (read)",
                  f"ProxyEnable={values['ProxyEnable']} ProxyServer={values['ProxyServer']!r} "
                  f"ProxyOverride={values['ProxyOverride']!r} AutoConfigURL={values['AutoConfigURL']!r}")

    if values["AutoConfigURL"]:
        _print_result(
            None, "PAC (proxy auto-config) script configured",
            f"AutoConfigURL={values['AutoConfigURL']!r} -- this script's timing test (below) CANNOT "
            "evaluate a PAC script the way WinINet does, so it may not surface a PAC-driven delay "
            "even when that is the real cause. Check manually: Control Panel > Internet Options > "
            "Connections > LAN Settings > 'Use automatic configuration script' -- try unchecking it "
            "temporarily to see if the EA's WebRequest() failures stop.",
        )
    return values


def _bypasses_loopback(proxy_override: str) -> bool:
    if not proxy_override:
        return False
    tokens = [t.strip().lower() for t in proxy_override.split(";")]
    return "<local>" in tokens or "127.0.0.1" in tokens or any(t.startswith("127.0.0.1") for t in tokens)


def _timed_request(url: str, use_system_proxy: bool) -> "tuple[float, str]":
    """Returns (elapsed_seconds, outcome). outcome is the HTTP status or
    an error description -- the status/error itself is irrelevant to this
    diagnostic, only how long WinINet-equivalent resolution took to
    produce *some* outcome, exactly mirroring what the EA's own
    TITAN_DIAG NO_RESPONSE/elapsedMs marker measures."""
    if use_system_proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies()))
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    start = time.monotonic()
    try:
        with opener.open(url, timeout=15.0) as resp:
            outcome = f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        outcome = f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 -- any failure still gives us a real elapsed time
        outcome = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - start
    return elapsed, outcome


def run_timing_comparison(bridge_host: str, bridge_port: int):
    url = f"http://{bridge_host}:{bridge_port}/bridge/heartbeat"
    print()
    print(f"Timing a real request to {url} (status/rejection reason is irrelevant -- only elapsed time matters):")

    system_elapsed, system_outcome = _timed_request(url, use_system_proxy=True)
    _print_result(True, "  With system proxy settings honored (mirrors WinINet/WebRequest())",
                  f"{system_elapsed:.2f}s -- {system_outcome}")

    direct_elapsed, direct_outcome = _timed_request(url, use_system_proxy=False)
    _print_result(True, "  With proxy explicitly bypassed",
                  f"{direct_elapsed:.2f}s -- {direct_outcome}")

    delta = system_elapsed - direct_elapsed
    print()
    if delta > 1.0:
        _print_result(
            False, "Proxy-resolution overhead detected",
            f"System-proxy-aware request took {delta:.2f}s longer than the direct request -- real, "
            "measured evidence that this machine's proxy configuration is adding delay to loopback "
            "requests, consistent with the field-observed pseudoStatus=1001/GetLastError=5203 "
            "signature (elapsed ~7000ms exceeding WebRequest()'s 5000ms timeout).",
        )
        return False
    _print_result(
        True, "No significant proxy-resolution overhead measured",
        f"Difference was only {delta:.2f}s. If WebRequest() failures are still occurring, this "
        "specific hypothesis (WinINet proxy/WPAD delay) is not confirmed by this test -- check the "
        "PAC-script caveat above, or investigate other causes (antivirus/EDR HTTP inspection, "
        "Windows Firewall, a VPS-provider network security agent).",
    )
    return True


def apply_fix(current_override: str) -> str:
    import winreg

    new_tokens = [t for t in current_override.split(";") if t.strip()]
    if "<local>" not in [t.strip().lower() for t in new_tokens]:
        new_tokens.append("<local>")
    if not any(t.strip() == "127.0.0.1" for t in new_tokens):
        new_tokens.append("127.0.0.1")
    new_override = ";".join(new_tokens)

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, new_override)
    key.Close()
    _print_result(
        True, "Applied fix: added loopback bypass to ProxyOverride",
        f"ProxyOverride is now {new_override!r}. ProxyEnable/ProxyServer were left untouched -- "
        "this deployment's own external calls (Trading Economics/Forex Factory news providers) may "
        "still legitimately need the configured proxy; only loopback traffic now bypasses it. "
        "A new MT5 terminal instance/process may need to restart to pick up the change (WinINet "
        "settings are typically re-read per-process, not live-reloaded).",
    )
    return new_override


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=str(_REPO_ROOT / "titan_protocol_config.json"))
    parser.add_argument("--fix", action="store_true",
                         help="add a loopback bypass to ProxyOverride if the diagnosis shows one is missing (see module docstring)")
    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        settings = load_settings(config_path)
        bridge_host, bridge_port = settings.bridge_host, settings.bridge_port
    except ConfigError as exc:
        print(f"Could not load {config_path}: {exc}")
        print("Falling back to the shipped default 127.0.0.1:8787 for this diagnostic.")
        bridge_host, bridge_port = "127.0.0.1", 8787

    print(f"Titan Protocol WinINet-layer diagnostic -- Bridge target: {bridge_host}:{bridge_port}")
    print()

    registry_values = read_proxy_registry()

    red_flag = False
    if registry_values is not None and registry_values["ProxyEnable"]:
        if not _bypasses_loopback(registry_values["ProxyOverride"]):
            _print_result(
                False, "Proxy enabled with no loopback bypass",
                f"ProxyEnable=1 and ProxyOverride={registry_values['ProxyOverride']!r} does not "
                "exempt 127.0.0.1/<local> -- WinINet will attempt proxy resolution for every "
                "WebRequest() call to the Bridge, even though it is on this same machine.",
            )
            red_flag = True
        else:
            _print_result(True, "Proxy enabled, but loopback bypass is present", "127.0.0.1/<local> is already exempted -- this specific cause is ruled out.")

    timing_clean = run_timing_comparison(bridge_host, bridge_port)
    if not timing_clean:
        red_flag = True

    if args.fix:
        print()
        if registry_values is None:
            print("Cannot apply --fix: proxy registry state could not be read (see above).")
            return 2
        if not registry_values["ProxyEnable"]:
            _print_result(True, "--fix skipped", "ProxyEnable=0 -- no proxy is configured, so there is no bypass list to fix.")
        elif _bypasses_loopback(registry_values["ProxyOverride"]):
            _print_result(True, "--fix skipped", "Loopback is already bypassed -- nothing to change.")
        else:
            new_override = apply_fix(registry_values["ProxyOverride"])
            print()
            print("Re-running the timing comparison to prove the fix actually changed something:")
            timing_clean = run_timing_comparison(bridge_host, bridge_port)
            red_flag = not timing_clean

    print()
    print("=" * 72)
    if red_flag:
        print("RESULT: red flag found -- see FAIL/INFO lines above for the exact evidence and next step.")
    else:
        print("RESULT: no red flag found by this script's own checks.")
    print("=" * 72)
    return 1 if red_flag else 0


if __name__ == "__main__":
    sys.exit(main())

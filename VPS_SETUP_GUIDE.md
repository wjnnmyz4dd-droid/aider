# VPS Setup Guide

Provisioning guide for the Windows VPS that runs Phantom in production
(PAPER or LIVE). This is an operational document — it does not describe
or authorize any change to trading logic.

## 1. Minimum VPS specification

- Windows Server 2019+ or Windows 10/11 Pro, x64.
- 4 vCPU / 8 GB RAM minimum (Phantom's own footprint is small; this
  headroom is for MT5 terminal + Python process + monitoring, not for
  running additional unrelated workloads on the same box).
- SSD-backed storage, 50 GB+ free (logs, backups, and MT5's own history
  cache all accumulate over time — see `DISASTER_RECOVERY.md`'s
  retention policy for how this is bounded).
- A low-latency network path to the broker's trade server — measure
  round-trip latency to the broker's server *before* committing to a
  VPS region; `ProductionMonitoring`'s `network_latency_ms` reading is
  only useful as an ongoing signal if the baseline is already good.

## 2. Software prerequisites

- MetaTrader 5 terminal, installed and logged in once manually to
  confirm the account/server/password combination is correct before any
  automation touches it.
- Python 3.11+ (matching this repository's tested version), with the
  `MetaTrader5` package installed for the real `MT5Adapter`
  (`phantom_pipeline/mt5_bridge/mt5_adapter.py`, Phase 3).
- This repository, cloned to a fixed path (e.g. `C:\phantom`), on the
  same branch/commit that passed the full validation suite.

## 3. Windows service registration

This package's `WindowsServiceManager`
(`phantom_pipeline/deployment/service_manager.py`) is a pure supervision
layer over injected `start`/`stop`/`is_running`/`is_responsive`
callables — it does not itself register a Windows Service. Two supported
ways to actually get a Windows Service entry for each managed process:

- **NSSM** (Non-Sucking Service Manager): wrap `python phantom_run.py` (or
  the MT5 terminal's own executable) as a Windows Service via `nssm
  install <ServiceName> <path> <args>`. Then `WindowsServiceManager`'s
  injected `start`/`stop` callables become `nssm start <ServiceName>` /
  `nssm stop <ServiceName>`, and `is_running` queries `sc query
  <ServiceName>`.
- **`pywin32`**: implement a native Windows Service using
  `win32serviceutil.ServiceFramework`, with the service's `SvcDoRun`
  invoking the same entry point NSSM would. Prefer this if you need
  Windows Event Log integration beyond what this package's own
  `logging_manager.py` already provides.

Either way, set every managed service (data feed process, Phantom core
process, dashboard process) to **Automatic (Delayed Start)** so the VPS's
own reboot does not race MT5 terminal's own startup; `ensure_started_after_reboot`
is the software-side backstop for anything that still needs a nudge.

## 4. Directories

Create and set permissions (VPS operator account only, no shared access)
for:

- `C:\phantom\logs\` — rotating + JSON logs (`logging_manager.py`).
- `C:\phantom\logs\archive\` — daily archives.
- `C:\phantom\crash_dumps\` — `generate_crash_dump` output.
- `C:\phantom\backups\` — `BackupManager`'s backup root.
- `C:\phantom\config\` — profile configuration (never the secrets
  themselves — see §5).

## 5. Secrets

Store `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER` and any broker API key as
**Windows environment variables** (System Properties → Environment
Variables) or a Windows Credential Manager entry read at startup — never
as plaintext in a file inside the repository clone.
`ConfigurationManager.load_profile` takes a plain mapping; the only
supported way to build that mapping in production is from the real
environment, never from a committed file.

## 6. Firewall / network

- Outbound: broker's MT5 server (whatever port your broker documents,
  typically an MT5-managed range), plus any Prometheus/monitoring
  endpoint (`phantom_pipeline/dashboard/prometheus_adapter.py`, Phase 3)
  if remote-scraped.
- Inbound: only the dashboard's own port, and only from a trusted
  management network — never expose it publicly.

## 7. Post-provisioning check

Before installing Phantom itself, run:

```
python -m compileall phantom_pipeline tests scripts
python -m unittest discover -s tests\phantom_pipeline
python validate.py
python scripts\check_architecture.py
```

All four must pass on the VPS itself, not just on the machine that built
the release — a clean checkout can still fail on a VPS missing a system
dependency (e.g. the real `MetaTrader5` package, which Phase 3's
`MT5Adapter` lazily imports and which is genuinely absent on non-Windows
CI).

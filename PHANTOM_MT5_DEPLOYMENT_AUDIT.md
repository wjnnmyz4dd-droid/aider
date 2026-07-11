# Phantom MT5 Deployment Audit

**Audit only. Nothing was deleted, moved, or modified.** This document
classifies every file in the repository and traces real imports (not
assumptions) to determine the minimum file set required to run Phantom
against MT5.

---

## 0. CRITICAL FINDING — read this before copying anything to the VPS

This repository contains **two entirely separate, non-interoperating
architectures**:

1. **`phantom/`** — the current, authoritative pipeline (Evidence →
   Market Intelligence → Strategy → Risk → Compliance → Runtime →
   Bridge), built ADR-024 through ADR-032. This is what CLAUDE.md's
   "Architecture authority" clause means by "ADR-001 and its per-stage
   successors" and is the system this session actually built and
   tested (2,558 passing tests as of the last Phase 3B report).
2. **`phantom_pipeline/`** — an older, superseded architecture
   (Scanner, Scoring Engine, old Strategy/Risk/Compliance Engines,
   Execution Validator, Position Manager, Analytics, Dashboard,
   Data Pipeline, Deployment, Knowledge, Research Desk, Paper Trading,
   Statistical Risk, Watchdog). CLAUDE.md explicitly calls this
   **"reference-only — mined for proven algorithms and safety
   mechanisms, neither is a running authority."**

**`DEPLOYMENT_PACKAGE/` (already present in this repo) is a snapshot of
`phantom_pipeline/`, not `phantom/`.** It was built in an earlier phase
before the `phantom/` architecture existed. **Do not copy
`DEPLOYMENT_PACKAGE/` to the VPS** — it is the wrong architecture for
every engine named in your mission (its "Strategy Engine," "Risk
Engine," and "Compliance Engine" are the old, superseded
implementations, and it has no Evidence Engine, Market Intelligence
Engine, Runtime Orchestrator, or Reliability Engine at all).

**A second finding, equally important: no production startup script
exists yet for `phantom/`.** I traced every import of
`RuntimeOrchestrator` in the repository — it is only ever imported by
`phantom/runtime/` itself and by the test suite. There is no
`start_phantom.py`, `main.py`, or equivalent that wires together the
five real engines, `phantom.bridge`, and `phantom.reliability` for live
trading. `START_PHANTOM.md` and `DEPLOYMENT_PACKAGE/`'s own
`start_phantom.py` are written for `phantom_pipeline/`, not `phantom/`.
**§7 below gives you the correct startup sequence and the exact
construction call your entry point needs to make — but you (or a
follow-up task) still need to write that entry point file.** I have
not written one myself, since doing so would be new production code,
outside this audit's scope.

Everything below classifies files against **`phantom/`** as the
system-of-record, consistent with those two findings.

---

## 1. Deployment Folder Tree

Exactly what should be copied to the VPS (traced imports only — every
file below is either directly imported by `phantom.runtime.engine` or
imported transitively by something that is).

```
phantom/
├── __init__.py                              REQUIRED_RUNTIME
├── bridge/                                  REQUIRED_RUNTIME  (leaf package, no internal cross-imports)
│   ├── __init__.py
│   ├── command_queue.py
│   ├── config.py
│   ├── connection_health.py
│   ├── engine.py
│   ├── logging_sink.py
│   ├── metrics.py
│   ├── models.py
│   ├── server.py
│   └── validation.py
├── evidence_engine/                         REQUIRED_RUNTIME  (leaf package, no internal cross-imports)
│   ├── __init__.py
│   ├── candlesticks.py
│   ├── config.py
│   ├── engine.py
│   ├── explainability.py
│   ├── indicators.py
│   ├── liquidity.py
│   ├── logging_sink.py
│   ├── metrics.py
│   ├── models.py
│   ├── ranking.py
│   ├── scoring.py
│   ├── session.py
│   ├── structure.py
│   ├── support_resistance.py
│   ├── trend.py
│   └── volatility.py
├── market_intelligence/                     REQUIRED_RUNTIME  (imports evidence_engine.{config,models,session})
│   ├── __init__.py
│   ├── config.py
│   ├── engine.py
│   ├── explainability.py
│   ├── liquidity_intelligence.py
│   ├── logging_sink.py
│   ├── market_safety.py
│   ├── metrics.py
│   ├── models.py
│   ├── news.py
│   ├── peg_policy.py
│   ├── scoring.py
│   └── session_intelligence.py
├── strategy_engine/                         REQUIRED_RUNTIME  (imports evidence_engine + market_intelligence models)
│   ├── __init__.py
│   ├── config.py
│   ├── eligibility.py
│   ├── engine.py
│   ├── explainability.py
│   ├── logging_sink.py
│   ├── metrics.py
│   ├── models.py
│   ├── selection.py
│   └── strategies/
│       ├── __init__.py
│       ├── _helpers.py
│       ├── base.py
│       ├── bos_fvg.py
│       ├── liquidity_sweep_mss.py
│       ├── range_reversal.py
│       ├── registry.py
│       ├── session_breakout.py
│       └── trend_continuation.py
├── risk_engine/                             REQUIRED_RUNTIME  (imports evidence_engine + market_intelligence + strategy_engine models)
│   ├── __init__.py
│   ├── confidence.py
│   ├── config.py
│   ├── correlation.py
│   ├── engine.py
│   ├── explainability.py
│   ├── exposure.py
│   ├── gate.py
│   ├── logging_sink.py
│   ├── metrics.py
│   ├── models.py
│   ├── monte_carlo.py
│   ├── position_sizing.py
│   ├── reservation.py
│   ├── safety_limits.py
│   ├── statistics.py
│   └── volatility.py
├── compliance_engine/                       REQUIRED_RUNTIME  (imports evidence_engine + market_intelligence + risk_engine + strategy_engine models)
│   ├── __init__.py
│   ├── bands.py
│   ├── compliance_score.py
│   ├── config.py
│   ├── consecutive_loss.py
│   ├── daily_loss.py
│   ├── drawdown.py
│   ├── engine.py
│   ├── explainability.py
│   ├── lock.py
│   ├── logging_sink.py
│   ├── market_conditions.py
│   ├── metrics.py
│   ├── models.py
│   ├── position_limits.py
│   ├── profit_protection.py
│   └── rule_profile.py
├── runtime/                                 REQUIRED_RUNTIME  (the orchestrator — imports all 5 engines above + bridge.models)
│   ├── __init__.py
│   ├── bridge_handoff.py
│   ├── config.py                            REQUIRED_CONFIGURATION (RuntimeConfig)
│   ├── engine.py
│   ├── logging_sink.py
│   ├── metrics.py
│   ├── models.py
│   ├── profiles.py                          REQUIRED_CONFIGURATION (the 6 Trading Profiles)
│   ├── validation.py
│   └── watchdog_integration.py
└── reliability/                             REQUIRED_RUNTIME  (external observer — imports only runtime.models/runtime.watchdog_integration)
    ├── __init__.py
    ├── config.py
    ├── degradation.py
    ├── engine.py
    ├── heartbeat.py
    ├── logging_sink.py
    ├── metrics.py
    ├── models.py
    ├── recovery.py
    ├── resource_monitor.py
    └── snapshot_freshness.py

mt5/
├── PhantomBridgeEA.mq5                      REQUIRED_RUNTIME       (the Phantom EA — verified its HTTP endpoints
│                                                                    exactly match phantom/bridge/server.py's
│                                                                    handlers: /bridge/heartbeat, /bridge/account,
│                                                                    /bridge/positions, /bridge/orders,
│                                                                    /bridge/trade-transaction, /bridge/error,
│                                                                    /bridge/execution/report,
│                                                                    /bridge/commands/poll — this is the correct,
│                                                                    matched EA for phantom/bridge, not a stray
│                                                                    file for some other bridge implementation)
└── PhantomBridgeEA.set                      REQUIRED_CONFIGURATION (EA input-parameter preset)

<NOT YET CREATED — see §0/§7>
└── start_phantom.py (or equivalent)         REQUIRED_DEPLOYMENT    (entry point; does not exist in this repo yet)
```

**File count: 131 Python files under `phantom/`** (excludes
`phantom/validation_engine/`, 19 files — see §4, it is a verification
authority, never imported by Runtime) **+ 2 files under `mt5/`.**

**Zero third-party pip dependencies.** Traced every top-level
`import`/`from` in `phantom/` — the only non-stdlib names found
(`hmac`, `http`, `urllib`) are all Python standard library. Nothing
needs to be `pip install`ed for `phantom/` itself.

**Zero imports of `phantom_pipeline`** anywhere in `phantom/` (grepped
the whole tree; the only 4 hits are comments/docstrings explicitly
stating this is a design invariant, not real import statements).

### REQUIRED_CONFIGURATION detail

There is currently **no external config file** (no `.env`, no `.yaml`,
no `.json`) for the `phantom/` architecture — configuration is
Python-code-only:
- `phantom/runtime/config.py` — `RuntimeConfig` dataclass (magic
  number, max slippage points, etc.)
- `phantom/runtime/profiles.py` — the 6 Trading Profile factories
  (`make_london_conservative_profile`, `make_london_aggressive_profile`,
  `make_new_york_conservative_profile`,
  `make_new_york_aggressive_profile`, `make_london_and_new_york_
  profile`, `make_custom_profile`)
- Every engine's own `config.py` (`EvidenceEngineConfig`,
  `MarketIntelligenceConfig`, `StrategyEngineConfig`,
  `RiskEngineConfig`, `ComplianceEngineConfig`, `phantom.reliability.
  ReliabilityConfig`, `phantom.bridge.BridgeConfig`) — all already
  listed above under `REQUIRED_RUNTIME` since they live inside each
  engine's own package.
- `mt5/PhantomBridgeEA.set` is the one genuine external configuration
  file, read by MT5 itself when the EA is attached to a chart.

If you want a real `config/` directory of environment files (dev/paper/
live), that would need to be authored fresh for `phantom/` — the
existing `DEPLOYMENT_PACKAGE/config/*.env.template` files are for
`phantom_pipeline/` and reference settings (e.g. `phantom_pipeline.
scanner`) that don't exist in the new architecture.

### REQUIRED_DEPLOYMENT detail

- The startup script named in §0 (does not exist yet).
- No `requirements.txt` is required for `phantom/` itself (zero
  third-party deps). If your entry point uses something like `psutil`
  for richer CPU/memory sampling than `phantom.reliability.
  resource_monitor`'s stdlib default, that would be the one dependency
  to pin — optional, not required (the stdlib sampler already works).
- MT5 terminal + the EA compiled from `mt5/PhantomBridgeEA.mq5`,
  attached to a chart with `mt5/PhantomBridgeEA.set` loaded, and
  `WebRequest` permissions granted for the bridge's base URL (default
  `http://127.0.0.1:8787` per the EA's `BackendUrl` input).

---

## 2. Documentation Folder (safe to keep on your dev machine only)

Everything at the repository root matching `*.md` (36 files) except the
two audit files this session produced (`PHANTOM_PHASE3B_RELEASE_
READINESS_REPORT.md`, `PHANTOM_PHASE3B_OPERATOR_GUIDE.md`) and this
one — all `OPTIONAL_DOCUMENTATION`:

```
ARCHITECTURE.md, AUDIT.md, CHANGELOG.md, COPY_TO_VPS.md,
DEPLOYMENT_AUDIT.md, DEPLOYMENT_MANIFEST.md, DISASTER_RECOVERY.md,
FINAL_DEPLOYMENT_READINESS_REPORT.md, IMPLEMENTATION_PLAN.md,
INTERFACE_SPECIFICATION.md, KNOWLEDGE_DEPLOYMENT_GUIDE.md,
LIVE_DEPLOYMENT_GUIDE.md, OPERATOR_CHECKLIST.md,
PHANTOM_ARCHITECTURE_HARDENING.md,
PHANTOM_BRIDGE_CONCURRENCY_HOTFIX_REPORT.md,
PHANTOM_BRIDGE_CONNECTION_HEALTH_HOTFIX_REPORT.md,
PHANTOM_BRIDGE_EA_PHASE1_FIX_REPORT.md, PHANTOM_BRIDGE_EA_PHASE1_REPORT.md,
PHANTOM_BRIDGE_EA_PHASE1_VALIDATION_PACKAGE.md,
PHANTOM_BRIDGE_EA_PHASE1_VERIFICATION_AUDIT.md,
PHANTOM_BRIDGE_PHASE1_5_VALIDATION_REPORT.md,
PHANTOM_BRIDGE_PHASE1_6_HARDENING_REPORT.md,
PHANTOM_COMPLIANCE_ENGINE_PHASE2E_REPORT.md,
PHANTOM_EVIDENCE_ENGINE_PHASE2A_REPORT.md,
PHANTOM_FINAL_ARCHITECTURE.md, PHANTOM_IMPLEMENTATION_ROADMAP.md,
PHANTOM_MARKET_INTELLIGENCE_PHASE2B_REPORT.md,
PHANTOM_RED_TEAM_AUDIT.md, PHANTOM_RESEARCH_ENGINE_PHASE2F_REPORT.md,
PHANTOM_RISK_ENGINE_PHASE2D_REPORT.md,
PHANTOM_RUNTIME_ORCHESTRATOR_PHASE3A_REPORT.md,
PHANTOM_STRATEGY_ENGINE_PHASE2C_REPORT.md,
PHANTOM_TECHNICAL_SPECIFICATIONS.md,
PHANTOM_VALIDATION_ENGINE_PHASE2G_REPORT.md, README.md, RELEASE.md,
RESEARCH_DESK_GUIDE.md, START_PHANTOM.md, VALIDATION_MATRIX.md,
VERIFY_DEPLOYMENT.md, VPS_SETUP_GUIDE.md
```

Plus:
- `docs/architecture/` (1 file) — `OPTIONAL_DOCUMENTATION`

---

## 3. Testing Folder (everything that can remain local)

All `OPTIONAL_TESTING`:

```
tests/                                    (299 test_*.py files, 25 _fixtures.py files)
├── phantom/bridge/
├── phantom/compliance_engine/
├── phantom/e2e/                          (Phase 3B cross-cutting validation suite)
├── phantom/evidence_engine/
├── phantom/market_intelligence/
├── phantom/reliability/
├── phantom/research_engine/
├── phantom/risk_engine/
├── phantom/runtime/
├── phantom/strategy_engine/
├── phantom/validation_engine/
├── test_account_snapshot.py              (legacy phantom_institutional test)
├── test_journal_fields.py                (legacy phantom_institutional test)
└── test_score_signal.py                  (legacy phantom_institutional test)
```

Also `OPTIONAL_TESTING`:
- `scripts/phase1_5_bridge_validation.py` — self-documented in its own
  docstring as *"a validation tool, not production code."*
- `phantom/validation_engine/` (19 files) — see §4; it is a
  verification/tournament/replay authority used to validate the other
  engines, never imported by `phantom.runtime` or by anything in the
  `REQUIRED_RUNTIME` list. It's arguably its own category (a testing
  *engine*, not unit tests), but it belongs on your dev machine either
  way — Runtime never calls it.

---

## 4. Research Folder (used only for future development)

All `OPTIONAL_RESEARCH`:

```
docs/adr/            (33 files — every Architecture Decision Record, including
                       ADR-001 through ADR-032; keep for institutional history,
                       never needed at runtime)
docs/specs/           (10 files — pre-implementation specs, several superseded
                       by the ADRs that followed them, e.g. docs/specs/00_
                       runtime_orchestrator.md predates the real engine
                       interfaces and is explicitly disclaimed as "ideas-only"
                       in ADR-031 itself)
docs/plans/           (10 files — RPI planning artifacts)
docs/research/        (7 files — external-repo research writeups, e.g. the
                       EA31337/MQL5-JSON-API-2/dwx-zeromq-connector audits)
docs/mt5_validation/  (8 files)
phantom_institutional.py   (root-level; CLAUDE.md explicitly calls this
                            "reference-only ... mined for proven algorithms
                            and safety mechanisms" — imports Flask, which
                            isn't even installed in this environment, so
                            it cannot run as-is regardless)
phantom_pipeline/     (20 top-level packages: analytics, compliance_engine,
                       dashboard, data_pipeline, deployment,
                       execution_validator, knowledge, mt5_bridge,
                       paper_trading, position_manager, research_desk,
                       risk_engine, scanner, scoring_engine, statistical_risk,
                       strategy_engine, watchdog — the entire superseded
                       architecture; see §0)
DEPLOYMENT_PACKAGE/   (a frozen snapshot of phantom_pipeline/ from an earlier
                       phase, plus its own config/scripts/VERSION.txt; see §0
                       for why this should NOT be copied to the VPS)
```

---

## 5. Unused Files

Nothing in the repository is genuinely dead/orphaned code in the
"never referenced by anything, including tests or docs" sense — every
file traces back to either the current architecture, the superseded
architecture (still referenced by its own tests/docs), or development
tooling. The closest things to `UNUSED`:

- `phantom/__pycache__/`, and every other `__pycache__/` directory
  throughout the repo, plus `.pytest_cache/` — compiled/cache
  artifacts, regenerated automatically, never deployed, safe to leave
  out of any copy operation (not "unused code," just build byproducts).
- `phantom_institutional.py` — cannot even run in this environment
  (imports `flask`, which is not installed), and is not imported by
  anything else in the repository. Classified under Research (§4)
  rather than a bare `UNUSED`, per CLAUDE.md's own characterization of
  it as a reference asset, but functionally it is dead weight for any
  deployment.

`OPTIONAL_DEVELOPMENT` (dev tooling, not "unused," but not part of any
of the four folders above either):
```
.claude/                       (agents, slash commands — Claude Code tooling)
.gitignore
scripts/check_architecture.py  (dev-only import-boundary checker, scoped to
                                 phantom_pipeline/ in its own current form)
```
No `.github/` directory exists in this repository (no CI workflows to
classify).

---

## 6. Import Trace (dependency graph, verified not assumed)

```
phantom.bridge            -> (no internal phantom.* imports; leaf)
phantom.evidence_engine    -> (no internal phantom.* imports; leaf)
phantom.market_intelligence -> phantom.evidence_engine.{config,models,session}
phantom.strategy_engine    -> phantom.evidence_engine.models
                            -> phantom.market_intelligence.models
phantom.risk_engine        -> phantom.evidence_engine.models
                            -> phantom.market_intelligence.models
                            -> phantom.strategy_engine.models
phantom.compliance_engine  -> phantom.evidence_engine.models
                            -> phantom.market_intelligence.models
                            -> phantom.risk_engine.{models,exposure}
                            -> phantom.strategy_engine.models
phantom.runtime.engine     -> phantom.bridge.models
                            -> phantom.evidence_engine.{engine,models}
                            -> phantom.market_intelligence.{engine,models}
                            -> phantom.strategy_engine.{engine,models}
                            -> phantom.risk_engine.{engine,models}
                            -> phantom.compliance_engine.{engine,models}
phantom.reliability         -> phantom.runtime.models
                            -> phantom.runtime.watchdog_integration
                            (never imports any of the 5 trading engines,
                             never imports phantom.runtime.engine itself —
                             it is fed Runtime's already-produced output by
                             an external caller, confirmed: RuntimeOrchestrator
                             is never imported inside phantom/reliability/)
phantom.research_engine     -> phantom.compliance_engine.models
                            -> phantom.evidence_engine.models
                            -> phantom.market_intelligence.models
                            -> phantom.risk_engine.{config,models,statistics}
                            -> phantom.strategy_engine.models
                            (never imported by phantom.runtime.engine —
                             confirmed by grep; it is an offline analytics
                             consumer of trade history, not a live-pipeline
                             dependency, matching ADR-029's own "advisory
                             only, read-only copy" design)
phantom.validation_engine   -> (not imported by phantom.runtime.engine or any
                             REQUIRED_RUNTIME file; a separate, independent
                             verification authority over already-recorded
                             snapshots)
```

**Conclusion: `phantom.research_engine` and `phantom.validation_engine`
are both real, working packages, but neither is imported by the live
trading path (`phantom.runtime.engine`).** Whether to include
`research_engine` in your VPS deployment is a judgment call, not an
import-tracing fact: if you want live trade-outcome analytics running
on the VPS, include it (it's cheap — no third-party deps, 17 files);
if analytics can run offline on your dev machine from exported trade
history, you can leave it off the VPS entirely. I've listed it under
Research (§4) as the conservative "only what Runtime literally imports"
reading, since your mission says "ONLY the files required to run the
system" — but flagging this judgment call explicitly rather than
silently deciding it for you.

---

## 7. Runtime Startup Order

This is the order `phantom.runtime.engine.RuntimeOrchestrator`'s own
constructor and `run_cycle()`/`run_cycle_for_pair()` methods actually
require, traced from the real code — **not** copied from any existing
(stale) doc:

1. **Load Configuration** — construct each engine's config object
   (`EvidenceEngineConfig()`, `MarketIntelligenceConfig()`,
   `StrategyEngineConfig()`, `RiskEngineConfig()`,
   `ComplianceEngineConfig()`, `phantom.bridge.BridgeConfig()`,
   `phantom.reliability.ReliabilityConfig()`, `phantom.runtime.
   RuntimeConfig()`), and select or build a `TradingProfile`
   (`phantom.runtime.profiles.make_*_profile()` or `make_custom_
   profile()`), then run it through `phantom.runtime.validation.
   validate_profile()` before proceeding — a profile that fails
   validation must never reach step 2.
2. **Construct the 5 core engines** — `EvidenceEngine(config)`,
   `MarketIntelligenceEngine(config)`, `StrategyEngine(config)`,
   `RiskEngine(config)`, `ComplianceEngine(config)` — each is
   independent and can be constructed in any order relative to each
   other, but all 5 must exist before step 3.
3. **Construct the Bridge** — `phantom.bridge.engine.BridgeEngine
   (config)` and start `phantom.bridge.server` (the `ThreadingHTTPServer`
   the EA's `WebRequest` calls will hit) — must be listening before the
   EA can successfully heartbeat.
4. **Construct the Runtime Orchestrator** — `RuntimeOrchestrator(
   config, evidence_engine, market_intelligence_engine, strategy_engine,
   risk_engine, compliance_engine, bridge_submit)`, where
   `bridge_submit` is a callable that hands a `TradeCommand` to your
   Bridge engine's command queue.
5. **Construct the Reliability Engine** — `ReliabilityEngine(config)` —
   independent of Runtime's construction, but your own supervisory loop
   needs a reference to both before step 7.
6. **(Optional) Construct the Research Engine** — if included per §6's
   judgment call — fed trade history/outcomes after cycles complete,
   never blocking a live decision.
7. **Start MT5 communication** — attach the compiled
   `PhantomBridgeEA.mq5` (with `PhantomBridgeEA.set` loaded) to a chart
   in MT5, with `WebRequest` permissions granted for the Bridge's base
   URL. The EA begins heartbeating and polling `/bridge/commands/poll`.
8. **Begin the cycle loop** — on each tick, call
   `orchestrator.run_cycle(pairs, profile, inputs, now, cycle_id)` for
   the profile's `allowed_pairs`, then `reliability.record_cycle
   (cycle_report)` and `reliability.report_heartbeat(...)` for each of
   the 4 restartable engines, `reliability.report_resource_usage(now)`,
   and `reliability.report_queue_depth(...)` for the Bridge command
   queue.
9. **Gate on `reliability.evaluate_health(now)`** — your supervisory
   loop (not Runtime, and not Reliability itself) decides whether to
   keep feeding cycles based on the returned `degradation_level` (see
   `PHANTOM_PHASE3B_OPERATOR_GUIDE.md` §4 for the exact response per
   level).

Steps 1-7 are one-time startup; steps 8-9 repeat every cycle.

---

## 8. Deployment Checklist

Every one of these must exist and be correctly wired before Phantom
can trade — checked against the real repository, not assumed:

- [x] `phantom/` package tree (131 files, §1) — present, compiles
      clean, 2,558 tests passing against it as of the last Phase 3B
      report.
- [x] `mt5/PhantomBridgeEA.mq5` + `PhantomBridgeEA.set` — present,
      endpoint-verified against `phantom/bridge/server.py`.
- [ ] **A production startup script wiring together configuration,
      the 5 engines, Bridge, Runtime, and Reliability per §7 — does
      NOT currently exist in this repository.** This is the single
      blocking gap between what's in the repo today and something you
      can actually start on a VPS.
- [ ] A real external configuration file (env/yaml/json) for
      dev/paper/live settings, if you want one — currently
      configuration is Python-code-only (§1's "REQUIRED_CONFIGURATION
      detail").
- [ ] MT5 terminal installed on the VPS, the EA compiled and attached
      to a chart, `WebRequest` allow-list updated with the Bridge's
      base URL, and network/firewall rules permitting the EA's
      loopback (or LAN) HTTP calls to reach `phantom.bridge.server`.
- [ ] A decision (not a fact — see §6) on whether `phantom/
      research_engine/` ships to the VPS or stays dev-machine-only.
- [ ] Log output destination configured — every engine logs through
      Python's stdlib `logging` module at `logging.getLogger("phantom.
      <package>")`; nothing currently calls `logging.basicConfig(...)`
      or attaches a file handler, so by default all output goes to
      stderr only. Your startup script should configure handlers
      (console + rotating file, or whatever your ops setup expects)
      before step 2 of §7.
- [ ] `DEPLOYMENT_PACKAGE/` explicitly **excluded** from the copy —
      confirmed stale (§0).

---

*This audit traced imports directly (via `grep` across every `.py`
file's `import`/`from` statements) rather than inferring dependencies
from documentation or naming conventions. No file was moved, deleted,
or modified in the course of this audit.*

# Session Edge — Analytics & Observability Ownership Map (PR-3M)

Status: **AUTHORITATIVE**. This document records the SINGLE canonical owner of every
analytics/observability responsibility, so no second authority is ever created. The
analytics layer is **observational only** — it has ZERO trading authority (never
authorizes/rejects/sizes/modifies a trade, stop, signal, score, risk, or volume, and
never touches a broker or bypasses compliance/news/session/FTMO).

## Single-owner map

| Responsibility | Canonical owner | Class |
|---|---|---|
| Per-trade realized R + win/loss FACT (one per signal_id, idempotent) | `manage/outcome.py::OutcomeReconciler` → `execution_outcome` MemoryStore record | AUTHORITATIVE |
| Expectancy, profit factor, drawdown, equity curve, win/loss/scratch, recovery, risk-adjusted, MAE/MFE aggregation | `research/portfolio.py` | AUTHORITATIVE (calculator) |
| Slippage / spread / latency / fill-quality stats | `research/execution_analytics.py` | AUTHORITATIVE (calculator) |
| Session / symbol / period breakdowns, tear sheet | `research/reporting.py` | AUTHORITATIVE (composer) |
| FTMO levels / report | `compliance/contract.py::ftmo_levels` (read-through by `research/reporting.ftmo_report`) | AUTHORITATIVE |
| Monte-Carlo, walk-forward, provenance/experiments | `research/montecarlo.py`, `research/walk_forward.py`, `research/provenance.py`, `research/experiments.py` | AUTHORITATIVE |
| **Lifecycle fact ingestion (NEW, PR-3M)** — stitch persisted `execution_outcome` facts into the trade records the calculators consume, + score-cohort readiness | `research/lifecycle.py` | AUTHORITATIVE (reader; recomputes nothing) |
| Trade lifecycle correlation key | `signal_id` (16-hex sha256) | AUTHORITATIVE |
| Audit facts (per stage) | 6 append-only JSONL writers (see below), unified by shared `bridge/atomic`+`bridge/serialize` and by `signal_id` | AUTHORITATIVE (per domain) |
| Reason-code vocabularies | 7 registries (see below) — REUSED, never redefined | AUTHORITATIVE |
| Health / status | per-domain status files + H5 `BridgeObservation` (see below) | AUTHORITATIVE (per domain) |
| Volume / lot sizing | `compliance/sizing.py` + `producer` (PR-3J) | AUTHORITATIVE — analytics never sizes |

`agents/offline/performance_analytics.py` is a **counting stub** (LIVE_AUTHORITY=False,
test-only) that returns record counts from the MemoryStore; it computes none of the
metrics above and is **not** a competing calculator. `research/lifecycle.py` is the
canonical analytics reader.

## Audit writers (correlation key)
- `bridge/audit.py::AuditLog` → `health/audit.jsonl` (signal_id)
- `compliance/audit.py::ComplianceAuditLog` → `compliance_audit.jsonl` (signal_id + decision_id)
- `producer/state.py::RunnerAudit` → `runner_audit.jsonl` (signal_id / cycle_id)
- `ea_mt5/position_manager.py::PMAudit` → `pm_audit.jsonl` (signal_id + ticket)
- manage audit → `manage/health/manage_audit.jsonl` (manage_id + signal_id + ticket)
- `agents/memory.py::MemoryStore` audit → `memory_audit.jsonl` (record id) — also holds the `execution_outcome` facts.

## Reason-code registries (reuse, never fork)
`bridge.contract.ReasonCode` / `ResultState`; `compliance.contract.ReasonCode`;
`position.contract.PMReason`; `producer.contract.RunnerReason` / `CycleOutcome`;
`manage.contract.ManageStatus`; `session.model.SessionReason`; execution `XReason`.

## Health / status authorities
`producer_health.json`, `manager_health.json`, `compliance_status.json`,
`session_status.json`, and the H5 `producer/bridge_health.py::observe_entry_bridge`
`BridgeObservation`. "Was broker state known?" = H5 (`bridge_healthy`/`missing_ack_count`)
+ `terminal_connected`. Analytics ingests these; it does not replace them.

## Fact provenance (never present an estimate as broker truth)
- **REALIZED_BROKER_FACT:** entry fill price/volume/slippage (entry result), exit
  `weighted_close`/`closed_volume` (MT5 deal history), symbol, direction.
- **DERIVED_METRIC:** realized `r_multiple` and `won` (from immutable entry/initial_stop
  + broker exit; single owner `manage/outcome.py`), and all `research/portfolio` stats.
- **UNAVAILABLE (never fabricated):** realized monetary P&L, MAE, MFE, commission,
  swap, per-trade `session`, and any numeric trade **score**.

## Trade SCORE — discrepancy (STOP-and-report)
There is **no numeric trade score** in Session Edge. The frozen engine emits binary
qualification (reason codes) plus a constant `confidence = 1.0`; the only continuous
numeric is `rr_planned` (gated at `min_rr`, not a graded score). Therefore the 70-based
score-cohort requirement has **no source fact today**: `research/lifecycle.py` defines
the cohort bands (70–74 … 95–100, sub-70 kept separate) and classifies every trade as
**UNAVAILABLE** until a score fact is added upstream. **No score-based sizing is
implemented.** This is deliberate evidence-readiness, not a fabricated score.

## Future score-based sizing boundary (NOT implemented in PR-3M)
If a future PR justifies score-sensitive risk, the ONLY permitted structure is:
`score → risk-tier policy → permitted risk_fraction/monetary budget → PR-3J canonical
sizing → authoritative volume → compliance verification → EA executes verbatim`.
There must remain ONE lot-size authority (PR-3J). Analytics never becomes a
`score → lot-size` calculator, and score never overrides FTMO/account/compliance limits.

## Third-party verification boundary
No Myfxbook / telemetry / external-export / HTTP surface exists in `forex_swing_orb/`
(dashboards are read-only status files). Internal analytics and any future third-party
verification remain independent evidence sources; no third-party service gets trading
authority.

# Titan Protocol Compliance Engine — Independent Architecture Review (Design-Only)

**Type:** Design-only, independent architecture review. **Read-only.**
**Authorization:** No Titan implementation changes are authorized. Titan source
is **not modified** by this document; this repository's review does not touch any
Titan artifact.
**Status of this review:** **INITIAL — REQUIRES REVISION** (see §12 disposition).
**Companion docs:** `docs/VIBE_TRADING_PHASE0_AUDIT.md` (audit; provisional Titan
decision in its §I) and `docs/FOREX_SWING_ORB_SPEC.md` (frozen Swing-ORB spec;
Execution Boundary §0.2, Trade Instruction Contract §8).

---

## 0. Scope, method, and a material limitation

**Review scope (as requested):** architecture, deterministic compliance logic,
execution gating, fail-closed behavior, ownership boundaries, risk controls,
auditability, state management, regression analysis.

**Method:** the review evaluates the Titan Protocol Compliance Engine **as
specified/decided so far** against those dimensions, using as the design basis:
(a) the provisional Titan decision (audit §I), (b) the frozen Swing-ORB Execution
Boundary and Trade Instruction Contract, and (c) the proven live-execution
primitives already present in Vibe-Trading (audit §D/§E: `sdk_order_gate`,
mandate/`HardCaps`, `halt` kill-switch, audit ledger) which are the natural
reference model for a compliance engine.

**Material limitation (must be stated up front):** the **Titan source repository
was not accessible in this session.** Discovery via GitHub repository search
returned no accessible Titan repo, and the account repo-list tool required an
approval that was not granted. Therefore this is a **design/specification-level
review, not a code audit.** Every finding about "current behavior" is a finding
about the *specified* behavior; a **source-level review is a required follow-up**
once read access to Titan is granted (§11 R-0). No finding here should be read as
a verified claim about Titan's actual code.

**Design contract being reviewed (restated from audit §I):**
- Titan is the preferred starting point for the lightweight MT5 execution EA.
- Titan does **not** own strategy research or qualification.
- Titan receives a **fully formed, versioned, expiring** trade instruction.
- Titan **independently enforces** account, symbol, duplicate-position,
  lot-size, stop-distance, spread, stale-signal, and kill-switch protections.
- Phantom risk/position logic may be **selectively evaluated** later; **no full
  Phantom merge** is authorized.

---

## 1. Ownership boundaries

**Intent (sound):** a clean separation — research/qualification upstream
(Vibe-Trading Swing-ORB `SignalEngine`), execution/compliance downstream (Titan).
The Swing-ORB Execution Boundary (spec §0.2) already forbids the strategy from
touching MT5/brokers, so the two halves meet only at the **Trade Instruction**
object. This is the correct seam.

**Findings:**
- **F-1 (finding, medium):** the boundary is asserted but not yet *contract-
  enforced*. There is no specified mechanism guaranteeing Titan will **reject any
  input that is not a schema-valid, version-matched, unexpired instruction**
  (spec §8). Without it, the "Titan does not do research" boundary is a
  convention, not an invariant.
- **F-2 (finding, low):** the review basis conflates "Titan (the EA/execution
  layer)" with "the Compliance Engine (the gate inside it)." The design should
  name the Compliance Engine as a **distinct, independently testable module** so
  that gating logic is not entangled with order-placement plumbing (mirrors
  Vibe-Trading's separation of `sdk_order_gate` from each connector's
  `place_order`).
- **F-3 (finding, medium):** ownership of **state** (open positions, daily
  counters, kill-switch flag, dedup ledger) is unspecified. If Titan trusts the
  broker/terminal as the sole source of truth, it inherits broker race
  conditions; if it keeps its own store, reconciliation rules must be defined
  (§8).

---

## 2. Architecture

**Findings:**
- **F-4 (medium):** no explicit module decomposition is specified. A compliance
  engine needs at least: `InstructionValidator` → `PreTradeGate` (ordered checks)
  → `Sizer` → `Executor adapter` → `AuditSink`, with a `KillSwitch` and a
  `StateStore` cross-cutting. Recommend adopting the Vibe-Trading shape
  (validator → ordered fail-closed checks under a lock → allow/deny → audit) as
  the reference architecture (audit §E, `sdk_order_gate.py:59`).
- **F-5 (medium):** **language/runtime is undecided in the design.** A native
  MQL5 EA (in-terminal) and a Python-side gate (out-of-terminal, using the
  existing `MetaTrader5` connector) have very different determinism, testability,
  and auditability properties. This choice gates almost every other dimension and
  must be made explicitly (§11 R-1). Vibe-Trading's `MetaTrader5` connector is
  Windows-only and already implements `order_send` behind a fail-closed gate —
  reusing it (Python-side) is far cheaper to test than re-implementing checks in
  MQL5.
- **F-6 (low):** the "lightweight" goal is in tension with the eight enforced
  protections + audit + state + regression harness. "Lightweight" should be
  defined as *minimal surface / no strategy logic*, **not** *minimal controls*.

---

## 3. Deterministic compliance logic

**Findings:**
- **F-7 (high):** the **order of checks is unspecified**, yet a compliance gate
  must apply checks in a **fixed, documented, deterministic sequence** so that the
  *reason* a trade is denied is reproducible. Recommend a canonical order:
  1) schema/version valid → 2) not expired (stale-signal) → 3) kill-switch not
  tripped → 4) symbol allowed → 5) no duplicate position → 6) spread within
  bound → 7) stop-distance within bound → 8) lot-size/notional within caps →
  9) account state readable. First failure denies; no later check can override.
- **F-8 (high):** **duplicate-position ("one per symbol") requires an atomic,
  idempotent guard.** Two instructions with the same `signal_id`, or two arriving
  concurrently for the same symbol, must not both open. The design must specify a
  **per-symbol lock + `signal_id` dedup ledger** (the frozen `signal_id` is
  content-deterministic, spec §8, which makes dedup reliable — a strong
  synergy to exploit).
- **F-9 (medium):** determinism must be defined against **inputs**: given the
  same instruction + same account/market snapshot, the decision must be
  identical. Any dependence on wall-clock (other than the explicit expiry check)
  or nondeterministic broker ordering breaks this and must be quarantined.

---

## 4. Execution gating

**Findings:**
- **F-10 (high):** gating must be **default-deny**: an instruction executes only
  if it affirmatively passes **every** check. This must be stated as an
  invariant, with the checks enumerated (§3 F-7).
- **F-11 (medium):** **stop-distance and lot-size** gates need concrete bounds
  and a defined interaction with the strategy's own values. The instruction
  already carries `stop_loss`/`entry_price` (spec §8); Titan must independently
  recompute the stop distance and lot from **its own** account equity and caps,
  and **reject** rather than silently resize if the strategy's implied size
  exceeds caps (mirrors Vibe-Trading `_size_guards`, audit §E).
- **F-12 (medium):** **spread and stale-signal** gates are time-sensitive and
  must be evaluated at the **moment of execution**, not at instruction receipt,
  because a queued instruction can go stale. Expiry (`expiration_timestamp`,
  spec §8.2) is the strategy-side bound; Titan must re-check it plus live spread.
- **F-13 (medium):** MT5-specific hazard carried from the audit: on **hedging
  accounts** an opposite-side order opens a hedge rather than closing, and MT5
  `place_order` exposes **no broker-side SL/TP** (audit §E). Titan's gate must
  therefore own SL/TP placement/monitoring and ticket-pinned closes — this is a
  first-class design requirement, not an edge case.

---

## 5. Fail-closed behavior

**Findings:**
- **F-14 (high):** fail-closed must be **total**: unreadable account state,
  unreadable kill-switch flag, unparseable instruction, missing market snapshot,
  or any exception in a check → **DENY**, never a default-allow. Vibe-Trading's
  `halt` treats an unreadable sentinel as tripped (audit §E) — adopt the same
  posture everywhere.
- **F-15 (medium):** the **kill-switch** needs defined scope (global vs per-
  symbol), a defined tripping authority (who/what can trip it), persistence
  across restarts (a filesystem/broker-side sentinel), and enforcement
  **independent of the strategy** (the strategy cannot un-trip it). This directly
  mirrors `agent/src/live/halt.py`.
- **F-16 (medium):** define behavior on **partial failure mid-sequence** (e.g.
  order accepted by terminal but audit write fails) — the design must state
  whether that is a reconcilable state and how it is detected (§8 state).

---

## 6. Risk controls

**Findings:**
- **F-17 (medium):** Titan must enforce **its own** risk envelope independent of
  the strategy: max per-trade risk, max concurrent exposure, daily/total loss
  limits, and max leverage — even though the strategy also enforces them
  (spec §9). Defense in depth: the strategy computing 0.25% does not absolve the
  gate from re-checking. Vibe-Trading's `HardCaps`
  (max_order_notional_usd/max_total_exposure_usd/max_leverage/max_trades_per_day)
  is a ready-made model (audit §E).
- **F-18 (medium):** **correlated-exposure** enforcement is out of scope for the
  single-symbol EURUSD baseline but must be a defined-but-dormant control so it
  is not retrofitted under pressure when a second pair is added.
- **F-19 (low):** the FX-notional-as-USD conservatism noted in the audit
  (over-deny pending FX normalization) is an acceptable initial posture for
  Titan too, but must be a **documented** choice, not an accident.

---

## 7. Auditability

**Findings:**
- **F-20 (high):** **every decision — allow and deny — must emit a structured,
  append-only audit record** keyed by `signal_id`, capturing the instruction, the
  account/market snapshot used, the ordered check results, the decision, and the
  resulting broker ticket (if any). Without allow+deny symmetry, a run's behavior
  is not reconstructable. This pairs with the strategy's own audit trail (spec
  §16 criterion 5) to give **end-to-end traceability** from setup → instruction →
  gate decision → execution.
- **F-21 (medium):** the audit sink must itself be **fail-closed-aware**: if the
  audit cannot be written, the safe default is to **deny** (an unaudited live
  order is worse than a missed trade). Define this explicitly.
- **F-22 (low):** define retention/rotation and that audit records **never**
  contain secrets (tokens, account credentials).

---

## 8. State management

**Findings:**
- **F-23 (high):** the **authoritative state model is undefined.** Required state:
  open positions per symbol, `signal_id` dedup ledger, daily/total realized PnL
  counters, kill-switch flag, and a "last reconciled-vs-broker" marker. Specify
  the store, its durability across restart, and its **reconciliation** rule vs the
  MT5 terminal on startup (Vibe-Trading has `live/runtime/reconcile.py` as prior
  art).
- **F-24 (medium):** **daily counters** need an explicit reset boundary (which
  timezone/rollover) consistent with the strategy's UTC-day loss controls
  (spec §9) to avoid a mismatch where the two halves disagree on "today."
- **F-25 (medium):** concurrency: if more than one instruction can be in flight,
  state mutations (dedup insert, position open, counter increment) must be under a
  lock and **only committed on confirmed non-error execution** (mirrors the
  Vibe-Trading daily-count-consumed-only-on-ALLOW rule, audit §E).

---

## 9. Regression analysis

**Findings:**
- **F-26 (high):** **no regression harness is specified.** A compliance engine
  must ship with a deterministic test battery that, for a fixed set of
  (instruction, account snapshot, market snapshot) fixtures, asserts the exact
  allow/deny decision and reason — and is run on every change so a check can never
  silently weaken. This is the single most important missing artifact.
- **F-27 (medium):** define **golden-file** decision fixtures (input → expected
  ordered-check outcome) so that any change in gating behavior is a visible diff.
- **F-28 (medium):** include adversarial fixtures: expired instruction,
  wrong `strategy_version`/schema version, duplicate `signal_id`, stop distance >
  cap, spread spike, kill-switch tripped, unreadable state — each must map to a
  specific deny reason.

---

## 10. Required revisions (to move toward ACCEPT)

Each maps to findings above. These are **design** revisions (no code authorized).

- **RR-1 (from F-5):** decide and document Titan's runtime (native MQL5 EA vs
  Python-side gate over the existing MT5 connector) with rationale; this is
  blocking.
- **RR-2 (from F-4/F-2):** publish a module decomposition naming the Compliance
  Engine as a distinct, independently testable unit.
- **RR-3 (from F-7/F-10):** specify the **canonical, fixed order of pre-trade
  checks** and the default-deny invariant.
- **RR-4 (from F-1/F-8):** specify **instruction validation** (schema + version +
  expiry) and the **atomic per-symbol + `signal_id` dedup** guard.
- **RR-5 (from F-14/F-15/F-21):** specify total fail-closed behavior, kill-switch
  scope/authority/persistence, and audit-write-failure = deny.
- **RR-6 (from F-20):** specify the **structured allow+deny audit schema** and its
  linkage to the strategy audit trail via `signal_id`.
- **RR-7 (from F-23/F-24/F-25):** specify the **state store**, restart durability,
  broker reconciliation, daily-reset boundary, and concurrency/locking.
- **RR-8 (from F-17/F-11):** specify Titan's **independent risk envelope** and the
  reject-don't-resize rule for cap breaches.
- **RR-9 (from F-13):** specify hedging-account handling and Titan-owned SL/TP
  monitoring + ticket-pinned closes.
- **RR-10 (from F-26/F-27/F-28):** specify the **deterministic regression harness**
  with golden-file decision fixtures incl. adversarial cases.

---

## 11. Recommendations

- **R-0 (access):** grant read access to the Titan repository and convert this
  design review into a **source-level audit** (the material limitation, §0).
- **R-1 (reuse over reinvent):** adopt Vibe-Trading's already-proven, already-
  tested live-gate primitives as the reference/candidate implementation:
  `sdk_order_gate` (ordered fail-closed checks under a lock), mandate/`HardCaps`,
  `halt` kill-switch, the audit ledger, and `runtime/reconcile.py`. This shrinks
  Titan's net-new surface to the MT5-specific and instruction-specific parts and
  reuses code that already has a passing test suite. **This is not a Phantom merge
  and not a Titan/Vibe merge — it is selecting a design pattern (and, later,
  possibly vendoring specific modules under explicit authorization).**
- **R-2 (Phantom, evaluation-only):** Phantom's `guards.py`/`risk.py`
  (spread/news/correlation/exposure/RR) may be **evaluated** as parity references
  for Titan's checks. No merge; no Phantom modification.
- **R-3 (exploit determinism):** the frozen, content-derived `signal_id`
  (spec §8) is a gift for dedup and audit-correlation — design the ledger and
  audit keys around it from day one.
- **R-4 (test-first):** land the regression harness (RR-10) **before** any gating
  logic, so every check is born with a golden decision fixture.
- **R-5 (staging):** never connect to a live account before the full battery
  passes on a demo/paper account with a demo↔paper identity guard (Vibe-Trading
  already models this posture, audit §D).

---

## 12. Acceptance matrix & final disposition

| # | Dimension | Design status | Blocking gaps (RR) |
|---|---|---|---|
| 1 | Ownership boundaries | **Partial** | RR-4 (contract-enforce the boundary) |
| 2 | Architecture | **Partial** | RR-1 (runtime), RR-2 (decomposition) |
| 3 | Deterministic compliance logic | **Insufficient** | RR-3, RR-4 |
| 4 | Execution gating | **Insufficient** | RR-3, RR-8, RR-9 |
| 5 | Fail-closed behavior | **Partial** | RR-5 |
| 6 | Risk controls | **Partial** | RR-8 |
| 7 | Auditability | **Insufficient** | RR-6 |
| 8 | State management | **Insufficient** | RR-7 |
| 9 | Regression analysis | **Missing** | RR-10 |
| — | Source verification | **Not performed** | R-0 (Titan source not accessible) |

**Legend:** *Sufficient* — specified to an implementable, testable standard;
*Partial* — intent agreed, key details missing; *Insufficient* — named but not
specified; *Missing* — absent.

### Final disposition: **REQUIRES REVISION**

The Titan Protocol Compliance Engine's **intent, ownership split, and required
protections are sound and correctly separated** from strategy research. However,
as a design artifact it is **not yet implementable or independently verifiable**:
the check ordering, instruction validation + dedup, fail-closed totality,
kill-switch semantics, audit schema, state/reconciliation model, and — most
critically — a **deterministic regression harness** are unspecified, and the
**Titan source could not be reviewed** in this session. Address RR-1…RR-10 and
grant source access (R-0) to progress toward **ACCEPT**. This is **not a REJECT**:
no design decision is fundamentally unsound; the gaps are specification depth and
verification, both closable without changing the agreed direction.

*No Titan implementation was inspected or modified. This review is design-only.*

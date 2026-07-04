# ADR-008 — MT5 Bridge

Status: Proposed

Owner: Backend Architect (Accountable per `.claude/agents/TEAM.md` §RACI
row "MT5 Bridge")

Reviewed by: Security Architect (Consulted per `TEAM.md`'s RACI — **not**
elevated to a mandatory gate the way `ADR-007`'s Execution row explicitly
was; TEAM.md draws that distinction deliberately and this ADR honors it
rather than inventing a stronger requirement), SRE (Consulted — connection
health, reconnect/heartbeat behavior is squarely its lane per `TEAM.md`
§"Watchdog function"). Software Architect is Informed per the same RACI
row, not a required reviewer.

Date: 2026-07-04

Depends on: `ADR-001-single-authority-architecture.md` (Accepted),
`ADR-002-scanner.md` (Accepted, including Amendment 1),
`ADR-003-strategy-engine.md` (Accepted), `ADR-004-scoring-engine.md`
(Proposed), `ADR-005-risk-engine.md` (Proposed),
`ADR-006-compliance-engine.md` (Proposed),
`ADR-007-execution-validator.md` (Accepted)

---

# Pipeline position

Market Data → Scanner → Strategy Engine → Scoring Engine → Risk Engine →
Compliance Engine → Execution Validator → **MT5 Bridge** → Position
Manager → Analytics

This ADR defines only the MT5 Bridge stage. It consumes the Execution
Validator's output (`ADR-007`) and is the sole component permitted to
communicate with MetaTrader 5. It does not define Position Manager
(`ADR-009`, not yet drafted), which is the intended consumer of the
synchronization and fill data this stage produces.

---

# 1. Mission

**The MT5 Bridge answers exactly one question: "How is an approved
execution request safely delivered to MetaTrader 5, and how are broker
responses safely returned?"**

It is a deterministic communications layer, not a trading engine, not a
strategy, not a risk engine, not a compliance engine. **It never decides
whether to trade.** Every decision it acts on was already made, in full,
by the stages before it.

---

# Hard Rules

These override any other requirement in this document if they ever
appear to conflict:

- **Accept only `ExecutionDecision` APPROVE.** Every request lacking a
  matching APPROVE is rejected before any broker communication is
  attempted — this is the binding requirement `ADR-007` §13 forward-
  declared on this ADR, and it is honored here as a hard gate, not a
  reference.
- **Never generate, approve, or block trades.** This stage transports a
  decision; it does not make one.
- **Never modify** `CandidateTrade`, `ScoreResult`, `RiskDecision`,
  `ComplianceDecision`, or `ExecutionDecision`. All remain immutable,
  read-only inputs.
- **Never recalculate anything** — not sizing, not SL/TP, not scores, not
  risk, not compliance, not validation. Translation to an MT5 request is
  a direct, faithful mapping of already-decided fields, never a
  re-derivation.
- **If connection fails → no order.** If acknowledgement fails → safe
  timeout. If synchronization fails → safe halt. **Never guess. Never
  retry blindly.**
- **No hidden execution path, no bypass, no emergency override.** Only
  the Execution Validator may authorize submission.

---

# 2. Responsibilities

The MT5 Bridge SHALL:

- Accept only `ExecutionDecision` APPROVE requests.
- Reject every request lacking `ExecutionDecision` approval.
- Translate Phantom objects (`CandidateTrade`, `RiskDecision`,
  `ExecutionDecision`) into MT5 order requests — a direct field mapping,
  never a re-derivation.
- Submit orders.
- Receive broker acknowledgements.
- Receive execution confirmations.
- Receive rejection reasons.
- Receive fill information.
- Receive position updates.
- Receive account updates.
- Maintain synchronization between Phantom's expectations and MT5's
  actual state.

---

# 3. The MT5 Bridge shall never

| Forbidden action | Owned instead by |
|---|---|
| Generate trades | Strategy Engine (`ADR-003`) |
| Modify `CandidateTrade` | Nobody — immutable (`ADR-003` §6) |
| Modify `ScoreResult` | Nobody — immutable (`ADR-004` §6) |
| Modify `RiskDecision` | Nobody — immutable (`ADR-005` §4) |
| Modify `ComplianceDecision` | Nobody — immutable (`ADR-006` §4) |
| Modify `ExecutionDecision` | Nobody — immutable (`ADR-007` §4) |
| Recalculate anything (sizing, SL/TP, scores, risk, compliance, validation) | The stage that already decided it |
| Approve trades | Execution Validator (`ADR-007`) |
| Block trades | Compliance Engine (`ADR-006`) |
| Manage positions | Position Manager (`ADR-009`, not yet drafted) |
| Close positions | Position Manager (`ADR-009`, not yet drafted) |
| Change SL/TP | Risk Engine (`ADR-005`) at decision time; no stage may change it post-decision without a fresh pipeline pass |
| Generate analytics | Analytics (`ADR-010`, not yet drafted) |

---

# 4. Inputs

- **`ExecutionDecision`** (`ADR-007` §4) — must be APPROVE; any other
  value, or its absence, is an unconditional reject before any broker
  call is made.
- **`RiskDecision`** (`ADR-005` §4), **`ComplianceDecision`** (`ADR-006`
  §4), **`CandidateTrade`** (`ADR-003` §6) — all read-only, via the
  shared `trace_id`, supplying the exact order parameters (direction,
  size, SL/TP) this stage transmits but never recalculates.
- **Broker state** — current connection/session state, read fresh.
- **Connection state** — the state-machine position this stage is
  currently in (§6).
- **Configuration** — timeout thresholds, reconnect policy, heartbeat
  interval, symbol/session mapping.

---

# 5. Outputs

One record per event, never discarded — the same "never fewer than one
output" discipline established at every prior stage. Each of the
following is a distinct output type, produced independently as the
corresponding broker event occurs (a single submitted order typically
produces several of these over its lifetime, not one combined record):

- **`BrokerRequest`** — the translated MT5 order request actually
  submitted, correlated to the originating `ExecutionDecision` by
  `trace_id` and this stage's own `execution_id` (§7).
- **`BrokerAcknowledgement`** — the broker's receipt confirmation that a
  request arrived, distinct from execution.
- **`ExecutionReceipt`** — confirmation that an order was executed by the
  broker.
- **`BrokerError`** — a rejection reason returned by the broker, distinct
  from a Phantom-side reject (which never reaches the broker at all).
- **`FillReport`** — fill price, fill size, fill timestamp.
- **`ConnectionStatus`** — current connection state-machine position
  (§6), updated on every transition.
- **`SynchronizationStatus`** — the outcome of the most recent
  reconciliation between Phantom's expected state and MT5's actual state
  (§9); the signal Position Manager (`ADR-009`) is expected to consume
  before acting on positions.

**Type-level guarantee:** none of these output types is structurally
capable of holding a modified upstream decision field or a new trading
instruction — the same guarantee established for every prior stage's
output type, verified by a dedicated test (§13).

**Immutability:** every output type, once produced, is immutable — it is
a record of what happened, not a mutable working object.

---

# 6. Connection management

- **Heartbeats** — a periodic liveness signal exchanged with the broker
  connection on a fixed interval (configuration, §4); a missed heartbeat
  beyond a configured threshold transitions the connection state machine
  toward Disconnected (below), never silently ignored.
- **Reconnect policy** — a bounded, backoff-based reconnect attempt
  sequence; reconnection does **not** imply resubmission of any order
  in flight — see Failure handling (§8) and Synchronization (§9) for what
  happens to state that was uncertain at disconnect time.
- **Session management** — broker session establishment and teardown are
  explicit state-machine transitions, not implicit side effects of order
  submission.
- **Timeout handling** — every broker call (submission, acknowledgement
  wait, position/account query) has a configured maximum wait; exceeding
  it is a timeout, handled per §8, never an indefinite wait.
- **Connection state machine** — at minimum: `Disconnected` →
  `Connecting` → `Connected` → `Synchronizing` → `Ready`, with any
  detected failure (missed heartbeat, broker error, timeout) transitioning
  back toward `Disconnected` rather than remaining in a stale `Ready`
  state. No order may be submitted outside the `Ready` state.
- **Order acknowledgement tracking** — every submitted `BrokerRequest` is
  tracked from submission until a terminal outcome (`ExecutionReceipt`,
  `BrokerError`, or a timeout resolved per §8) is reached; the Bridge
  never loses track of an order's outcome silently.

---

# 7. Idempotency

**This is a second, independent layer of idempotency from `ADR-007` §7's
duplicate-request handling, not a duplication of it.** `ADR-007` §7
prevents a duplicate `ExecutionDecision` APPROVE from being produced for
the same trade at the decision layer. This section prevents a duplicate
*submission to the broker* at the transport layer — e.g. a Bridge restart
mid-flight, a transport-level retry, or a replayed message — from
resulting in two orders reaching MT5 for what was, at the decision layer,
a single approved trade. Defense-in-depth between the two layers is
deliberate: either one failing alone must not produce a duplicate order.

- **Every request must carry a unique execution identifier
  (`execution_id`)**, derived from the `ExecutionDecision`'s `trace_id`,
  generated once per approved trade before submission.
- **Duplicate order submission** for the same `execution_id` is refused —
  a second submission attempt is rejected before it reaches the broker,
  not merely logged after the fact.
- **Replay** — a resubmitted or retried message carrying an
  already-seen `execution_id` is treated identically to a duplicate
  submission, refused.
- **Duplicate fills** — a `FillReport` referencing an `execution_id` this
  stage has already recorded a terminal fill for is flagged, not silently
  accepted as a second, additional fill.
- **Duplicate acknowledgements** — a repeated `BrokerAcknowledgement` for
  an already-acknowledged `execution_id` is recorded as a duplicate
  signal, not treated as two separate submissions.
- This record is bounded and TTL-pruned, mirroring the same discipline
  `ADR-007` §7 established for its own idempotency record — unbounded
  growth here would repeat the same class of defect flagged elsewhere in
  the reference material.

---

# 8. Failure handling

- **If connection fails: no order.** An order is never submitted outside
  the `Ready` connection state (§6). This is unconditional.
- **If acknowledgement fails: safe timeout.** A bounded wait, per the
  configured timeout (§6); on expiry, the order's outcome is **unknown**,
  not assumed. The Bridge must query broker state (open orders,
  positions) to determine the actual outcome before taking any further
  action — it never assumes the order succeeded, and never assumes it
  failed, either of which could produce a duplicate submission or a
  silently lost trade.
- **If synchronization fails: safe halt.** No new order is submitted
  while `SynchronizationStatus` (§9) indicates a discrepancy between
  Phantom's expected state and MT5's actual state. Resolving an existing
  discrepancy is Position Manager's (`ADR-009`) responsibility, not this
  stage's — the Bridge's own authority here is limited to detecting the
  discrepancy and halting new submissions, never to deciding how to
  reconcile it.
- **Never guess. Never retry blindly.** No automatic resubmission of an
  order whose outcome is unknown; reconciliation (§9) must resolve the
  outcome first.

---

# 9. Synchronization

- **Order synchronization** — every order this stage tracks (§6) is
  reconciled against the broker's own order/position records on
  reconnect and on a periodic cadence, not only at submission time.
- **Position synchronization** — Phantom's expected open positions are
  compared against MT5's actual open positions; a mismatch is reported
  via `SynchronizationStatus`, not silently resolved by this stage.
- **Account synchronization** — equity/margin/balance are compared
  against the account state assumed by upstream stages; drift is
  reported, not corrected here.
- **Fill synchronization** — fills received are reconciled against
  submitted orders by `execution_id`; an unmatched fill is a
  synchronization failure, not silently attributed to the nearest
  pending order.
- **Heartbeat synchronization** — a connection reporting `Ready` without
  a recent successful heartbeat is treated as desynchronized, not
  silently trusted.
- **Recovery after disconnect** — on reconnect, the Bridge queries
  broker-side truth (open positions, pending orders, account state)
  before resuming submission, and reconciles it against its own
  pre-disconnect expectations; any discrepancy triggers the safe halt
  in §8, surfaced as `SynchronizationStatus`, until Position Manager
  (`ADR-009`) resolves it. This ADR does not define that resolution
  process — only that this stage detects and reports, never silently
  overwrites its own expectations with broker state or vice versa.

---

# 10. Security

- **No hidden execution path. No bypass. No emergency override. Only
  Execution Validator may authorize submission.** (Hard Rules.)
- **The MT5 Bridge is the sole stage in the entire pipeline whose
  credentials include order-placement capability.** Every prior stage
  (`ADR-002` through `ADR-007`) is explicitly scoped, at the credential
  level, to have no order-placement capability whatsoever — that
  least-privilege guarantee is meaningful specifically because this
  capability is concentrated here alone, in the one stage whose entire
  purpose requires it.
- All upstream inputs (`ExecutionDecision`, `RiskDecision`,
  `ComplianceDecision`, `CandidateTrade`) are read-only; none are
  mutated.
- The idempotency record (§7) is protected against tampering — a
  compromised or buggy component clearing it to force a duplicate
  submission would defeat its entire purpose.

---

# 11. Logging

Every event is logged:

- Submission
- Acknowledgement
- Execution
- Reject
- Fill
- Disconnect
- Reconnect
- Timeout
- Synchronization (status change)

Every logged event carries `trace_id` (inherited from `ExecutionDecision`,
extending the chain from Scanner through every prior stage) and
`execution_id` (§7), making every broker interaction attributable to a
specific decision without re-running anything — the same explainability
discipline established at every prior stage.

---

# 12. Metrics

- Submission latency
- Broker latency
- Reconnect count
- Timeout count
- Reject count (broker-side, distinct from Phantom-side pre-submission
  rejects)
- Fill latency
- Heartbeat status
- Synchronization status
- Export-only, additive — the same discipline established at every prior
  stage.

---

# 13. Testing

- **Unit tests** — isolated, fixture-based, no dependency on a live
  broker connection.
- **Disconnect tests** — a mid-flight disconnect produces a safe halt
  (§8), never a silent loss of order state.
- **Reconnect tests** — reconnection triggers reconciliation (§9) before
  any new submission is permitted.
- **Duplicate submission tests** — a repeated submission for the same
  `execution_id` is refused (§7).
- **Duplicate fill tests** — a repeated `FillReport` for an already-filled
  `execution_id` is flagged, not accepted as an additional fill (§7).
- **Heartbeat tests** — a missed heartbeat transitions the connection
  state machine correctly (§6).
- **Synchronization tests** — an injected mismatch between expected and
  actual broker state produces `SynchronizationStatus` reporting the
  discrepancy and halts new submissions (§8, §9).
- **Broker rejection tests** — a `BrokerError` is correctly attributed to
  the originating `execution_id` and does not affect any other in-flight
  order.
- **Timeout tests** — an acknowledgement timeout resolves to reconciled
  query, never an assumed outcome (§8).
- **Replay tests** — a replayed message carrying a previously-used
  `execution_id` is refused (§7).
- **Boundary/type-level test** — no output type (§5) can hold a modified
  upstream decision field or a new trading instruction.
- **Trace-propagation test** — `trace_id` and `execution_id` are present
  and correct on every logged event and every output object.

---

# 14. Architectural invariants

- `ExecutionDecision` is immutable.
- The MT5 Bridge never changes trading decisions.
- Broker communication never bypasses the Execution Validator.
- Every execution is traceable, end to end, by `trace_id`.

---

# 15. Acceptance criteria

ADR-008 is acceptable only if it guarantees:

- ✓ No trade may reach MT5 without `ExecutionDecision` APPROVE (§1, Hard
  Rules).
- ✓ No duplicate execution — at both the decision layer (`ADR-007` §7)
  and the transport layer (§7).
- ✓ No hidden execution path (§10).
- ✓ No trading logic — no generation, approval, blocking, sizing, or
  recalculation of any kind (§3).
- ✓ Deterministic behavior — the translation from decision to broker
  request is a direct field mapping, never a re-derivation (Hard Rules,
  §2).
- ✓ Full traceability — every output and every logged event carries
  `trace_id` and `execution_id` (§11, §13).

---

# 16. Reference material — ideas only, not authority

- **No dedicated MT5 broker-communication module exists anywhere in this
  repository** (verified: no `MetaTrader5` import, no `order_send`, no
  broker-facing code in `phantom/` or `phantom_institutional.py`). Unlike
  every prior ADR, there is no legacy "bridge" file to mine for ideas —
  this stage is designed entirely from first principles, consistent with
  the instruction that no legacy implementation is authoritative.
- `phantom/trade_router.py`'s account-feed staleness handling
  (`"stale account feed"`, `"account-feed-error (fail-closed)"`) — the
  direct idea behind this ADR's fail-closed philosophy (§8) and its
  synchronization staleness handling (§9), generalized from account-feed
  freshness specifically to connection/order/position/fill freshness
  generally. `trade_router.py` itself is a sizing module, not a broker
  bridge, and is not otherwise reused here.
- `phantom_institutional.py` — has no distinct broker-communication layer
  separate from decision logic; wherever order-facing code might exist,
  it is not isolated from scoring/risk/compliance concerns. Studied as a
  negative example, the same pattern every prior ADR's reference-material
  review has identified for this file.

---

Per `ADR-001` and `CLAUDE.md` §1.10, **no implementation begins until this
ADR's Status changes from Proposed to Accepted.**

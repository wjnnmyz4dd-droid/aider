# Consolidated Architecture Report — New Phantom

Status: **Design proposal only. No code written. No ADRs created. No
existing file modified.** This report itself is a new, additive
document. Stop after this report and wait for approval before any
implementation begins.

## Sources used (and one honest gap)

This report draws **only** on research already completed and delivered
in this conversation:

1. **Phantom internal architecture audit** — two of three planned
   research threads completed and used here: (a) a cross-stage
   decision-authority overlap audit (spread checks, risk/exposure
   decisions, kill-switch ownership, execution paths) and (b) a legacy
   `phantom/` + `phantom_institutional.py` vs. `phantom_pipeline/`
   duplication audit, plus facts I verified directly (DEPLOYMENT_PACKAGE
   staleness, `validate.py`'s actual test scope, the legacy `tests/`
   suite). **The third planned thread — a full dead-code/unused-function
   scan and an orchestrator-wiring table for all 18 `phantom_pipeline/`
   packages — never returned a result and is not used here.** Where this
   report needs that information and doesn't have it, it says so rather
   than guessing.
2. **`docs/research/mql5-json-api-2-audit.md`** — complete.
3. **`docs/research/dwx-zeromq-connector-audit.md`** — complete.

Per your explicit instruction, `EA31337`/`EA31337-classes`/`EA31337-strategies`
findings are **not** used anywhere in this report — that material was
removed from the project and is being treated as if it never existed.
`backtrader`, `TA-Lib`, and the MetaTrader 5 Standard Library have not
been researched yet and are also not used here; the architecture below
may be revised once those are complete.

---

## 1. Every concept worth keeping

**From Phantom's own existing design (validated by contrast with both
external repos, not merely assumed):**
- HTTP + API-key transport for the EA↔Python bridge, over `WebRequest()`
  — no compiled DLL, no wildcard bind, real authentication. Both
  external repos use raw sockets with zero authentication; this
  reconfirms Phantom's existing choice was already correct.
- Validate-then-acknowledge command handling — never confirm receipt as
  a proxy for validity. MQL5-JSON-API-2 gets this wrong (ack sent before
  validation); dwx-zeromq-connector gets it right (ack built from the
  real post-execution outcome) — Phantom's design must keep matching
  the correct version.
- Idempotent, server-issued command IDs correlating a request to its
  result. Neither external repo has an equivalent.
- A single, durable kill-switch authority (Compliance Engine in the
  current implementation) that every other stage only *consumes*, never
  independently recomputes — confirmed properly layered in the internal
  audit, with Position Manager correctly taking it as an input rather
  than owning its own copy.
- A single execution chokepoint — exactly one place in the codebase
  ever calls "send this to the broker." Confirmed true internally.
- Fail-closed timeout as a hard requirement, not an afterthought. Both
  external repos lack this entirely.

**From the two external bridge audits (things they do right, worth
keeping as design invariants going forward):**
- Ack built from the real post-execution outcome, never sent before
  execution is attempted (dwx-zeromq-connector).
- A centralized, single-checklist pre-trade capability gate — one
  function enumerating every precondition (trade allowed, connection
  live, terminal ready, etc.) with a distinct rejection reason per
  failure, rather than checks scattered across the codebase
  (dwx-zeromq-connector's `CheckOpsStatus` pattern).
- Magic-number (or equivalent) isolation actually wired into every
  order-placing call, not merely declared in a schema
  (dwx-zeromq-connector, partially).

## 2. Every concept that should be improved

- **Magic-number/isolation scoping must apply to every operation, with
  no privileged "everything" exception.** dwx-zeromq-connector enforces
  it for order creation and selective close, but its bulk-close and
  list-all operations bypass it entirely — a concrete example of a gap
  to close by design rather than by convention.
- **Independent trade-transaction mirroring as a cross-check.** Both
  external repos (in different forms) hook the platform's own
  trade-transaction event as a channel independent of the bridge's own
  execution-reporting code — a good drift-detection idea worth adapting,
  never treated as more authoritative than the validated command itself.
- **Explicit "gap" signaling on market-data reconnection**, rather than
  silently resuming — both external repos have a version of this for
  market-data feeds; worth carrying forward for Phantom's bar/tick
  delivery.
- **`DEPLOYMENT_PACKAGE`'s build process** (internal finding): confirmed
  stale relative to the current source tree (missing the newest package
  at time of audit) — any deployment-snapshot mechanism the new
  architecture uses must not silently drift; it should be regenerated
  or verified as part of every release, not treated as a one-time copy.
- **`validate.py`'s actual scope vs. its documented role** (internal
  finding): the existing repo's primary "run the full validation suite"
  script tests only the legacy system, not the current one, despite
  being described as validating "the full suite." Any validation
  entry point in the new architecture must test what it claims to test,
  verified by what it actually imports — not assumed from its name.

## 3. Every concept that should be removed

*(Internal Phantom findings only — external repos contributed nothing
to "remove" since nothing from them is being adopted as running code in
the first place.)*

- **Legacy `phantom/` and `phantom_institutional.py`.** The internal
  audit confirmed both are now fully orphaned: no live/deployment path
  references either one; the only consumers are `validate.py`,
  `run_demo.py`, and a legacy test suite that tests them in isolation.
  Per your "forget the previous architecture... do not preserve
  packages, files, ADRs, or implementations unless they earn their
  place" directive, neither earns a place in the new architecture as
  running code. (Whether their *algorithms* are worth mining as
  inspiration is a separate question from whether the files themselves
  belong in the new system — the answer to the latter is no.)
- **The legacy test suite testing those files** (`tests/test_pipeline.py`,
  `tests/test_orchestrator.py`, `tests/test_playbooks_7_8.py`,
  `tests/fixtures.py`, `tests/test_account_snapshot.py`,
  `tests/test_score_signal.py`, `tests/test_journal_fields.py`) and
  `run_demo.py` — these exist solely to validate code that itself is
  being removed.
- **`validate.py` in its current form** — it validates a system that no
  longer exists in the new architecture; a from-scratch validation
  entry point needs to be designed against whatever the new system
  actually is, not inherited as-is.
- **The entire 18-package `phantom_pipeline/` structure, as a structure**
  — not because any individual package's *logic* is bad (the internal
  audit found the risk/compliance/execution layering to be sound), but
  because it does not match the minimal 7-component shape you've
  specified, and because — per the explicit instruction to rebuild from
  scratch — no package earns automatic carryover. Specific algorithms
  from it (e.g., the risk_engine constraint functions' overall shape,
  the position_manager lifecycle rules) may be worth reimplementing
  fresh inside the new Risk Engine component, but that is a decision to
  make deliberately per-concept during implementation, not an inherited
  default.

## 4. Every concept that should never be implemented

Consolidated from both external audits (see each report's own §9 for
full detail):

1. Acknowledging receipt of a command before validating it.
2. A schema field that implies a safety guarantee (isolation, auth,
   whatever) without it being provably enforced end-to-end.
3. Binding any trading-command channel to a wildcard interface with no
   authentication.
4. Trading indefinitely with no fail-closed timeout if the counterpart
   goes silent.
5. Fire-and-forget delivery for anything execution-critical, with no
   durable record and no correlation back to the request that caused it.
6. Shipping an "EXPERIMENTAL — DO NOT USE" module wired into a default
   build path.
7. `eval()` (or any general-purpose code-execution deserializer) for
   parsing anything received over a network channel.
8. A "close everything" / "list everything" administrative operation
   that bypasses the same scoping every other operation enforces.
9. A heartbeat/liveness primitive that exists in the protocol but isn't
   wired to an actual enforced action.
10. A native compiled-DLL dependency for the EA↔Python transport layer.

## 5. Every security improvement discovered

- Validate before acknowledging, always (dwx-zeromq-connector gets this
  right; MQL5-JSON-API-2 doesn't — adopt the correct version as an
  invariant).
- Enforce isolation (magic number or equivalent) on every mutating and
  every reading operation, with no exception — not just the operations
  the original author remembered to filter (dwx-zeromq-connector's
  partial enforcement is the cautionary half of this lesson).
- Never deserialize network data with `eval()` or an equivalent
  general-purpose executor — always a strict schema-validating parser.
- Never bind a trading-command channel wildcard with no authentication —
  confirmed as a real, exploitable gap in both external repos.
- Idempotent, server-issued command IDs as the sole mechanism for
  detecting and rejecting a duplicate/replayed command — neither
  external repo has any replay protection at all.
- A single, durable, exclusively-owned kill-switch authority, with every
  other component consuming (never recomputing) its state — confirmed
  as already correctly designed internally; must be preserved as an
  invariant in the new architecture, not just a description of the old
  one.

## 6. Every communication improvement discovered

- HTTP + `WebRequest()` over raw ZeroMQ sockets — no compiled DLL, no
  native-code trust boundary added to the terminal, portable to MT5
  without architecture-specific binaries. Both external repos require a
  DLL; both maintainers' own trajectories (one archived-in-spirit, one
  explicitly stated as heading for archival in favor of a DLL-free
  successor) reinforce this was the right call.
- A structured, versioned JSON message contract, not positional
  delimited strings or Python-dict-literal text requiring `eval()` to
  parse.
- Correlating a command's result back to the specific request that
  caused it via a stable ID — neither external repo does this reliably
  (MQL5-JSON-API-2 has no correlation at all across its split
  ack/result sockets; dwx-zeromq-connector's PUSH/PULL pairing is
  positional/sequential, not ID-correlated).
- Separating command/response traffic from unsolicited market-data
  broadcast into distinct channels — both external repos do this at the
  socket level; Phantom's endpoint-per-purpose HTTP design already
  achieves the same separation.
- A centralized, single-checklist precondition gate before any command
  executes, each failure mapped to a distinct, named reason
  (dwx-zeromq-connector's `CheckOpsStatus` pattern) — worth adopting as
  the shape of the new bridge's own pre-execution gate.
- Explicit "gap" signaling on reconnection for market-data channels,
  rather than silent resumption.

## 7. Every execution improvement discovered

- Build the execution result from the real, post-attempt broker
  response — never from anything computed before the attempt.
- A single execution chokepoint in the codebase — exactly one place
  ever submits an order to a broker/terminal — confirmed as already
  correctly designed internally and must remain a structural invariant,
  not merely a convention, in the new architecture.
- Named platform-error → stable-string translation, so client-side
  code (and humans) get a consistent, documented reason for every
  failure rather than a raw platform error code.
- Isolation (magic number or equivalent) enforced at the point of every
  order-affecting call, with a test proving a foreign-isolation-tagged
  order is never touched.
- An independent, platform-native trade-event mirror as a drift-detection
  cross-check against the bridge's own execution-reporting path.

## 8. Every risk-management improvement discovered

Neither external bridge repo implements any risk-management logic at
all — both are pure transport layers with, at most, a lot-size/order-count
ceiling. The risk-management improvements below come entirely from the
**internal Phantom audit**, which found the existing design already
sound and worth preserving as invariants in the new architecture rather
than as inherited code:

- Position sizing and the account-wide kill-switch must be **two
  distinct authorities with two distinct purposes** — one scales size
  down progressively, the other hard-blocks and can trip a durable
  lockout — never merged into one function, and never allowed to
  silently disagree because they read the same fact for different
  reasons.
- A risk-decision stage should never independently recompute a quantity
  another stage already decided — it should consume that stage's
  already-produced decision object. Confirmed true of the existing
  Risk/Compliance/Execution boundary internally; must be preserved as a
  design rule, not just a historical fact about deleted code.
- Any "read-only, advisory" statistical/analytical risk computation
  (e.g. Monte Carlo, Kelly-criterion sizing recommendations) must be
  structurally incapable of gating, altering, or delaying a trade
  decision — confirmed true internally and directly maps onto this
  report's Intelligence component (§ below), which must be
  architecturally advisory-only in the new system, not just documented
  as such.

## 9. Every anti-pattern discovered

Consolidated (see the two audit reports' own anti-pattern sections for
full detail):

1. Ack-before-validation.
2. Decorative/unenforced safety-looking schema fields.
3. Wildcard-bound, unauthenticated trading-command sockets.
4. No fail-closed timeout on counterpart liveness.
5. `eval()`/unsafe deserialization of network data.
6. Unscoped "everything" operations alongside otherwise-scoped ones.
7. A heartbeat/liveness primitive that exists but isn't wired to an
   enforced action.
8. Fire-and-forget delivery for execution-critical confirmations, with
   no durable record.
9. Hard dependency on a compiled, platform-specific DLL for core
   transport.
10. (Internal) A validation/test entry point that doesn't actually test
    what its name and documented role claim it tests — discovered in
    the existing `validate.py`, worth guarding against explicitly in
    whatever the new architecture's validation story is.
11. (Internal) A deployment-snapshot mechanism that can silently drift
    out of sync with the source it's supposed to mirror.

## 10. Every lesson learned

1. A regulated, well-resourced organization's reference code (darwinex)
   is not automatically safer than an independent hobbyist's — both
   audited repos share the identical zero-authentication,
   no-fail-closed-timeout defects despite very different provenance.
   Provenance buys credibility on documentation and breadth of
   adoption, not on security posture — verify the actual mechanism,
   every time.
2. A safety-looking field or primitive that isn't provably wired
   end-to-end (magic number, heartbeat) is actively worse than not
   having it, because it creates false confidence. Every safety
   guarantee the new architecture claims must have a test proving it
   holds, not just a schema field or a doc comment asserting it.
3. Fewer channels/sockets is not the same as better security — dwx-
   zeromq-connector has 3 sockets vs. MQL5-JSON-API-2's 7, and is no
   safer for it. Channel count is a communication-clarity question,
   authentication/validation is an orthogonal question, and conflating
   them is a mistake to avoid.
4. The single most consistent, most serious gap across both external
   repos is the complete absence of fail-closed behavior on client
   liveness. This is the single highest-priority invariant to protect
   in the new architecture's bridge design.
5. Internally: a system can look like it has a coherent, single-authority
   risk/compliance/execution boundary and mostly does — but "mostly"
   isn't good enough for an institutional system; the one narrow gap
   found (two supposedly-independent spread checks reusing the same
   market snapshot object rather than each fetching fresh data)
   illustrates how an architecturally-sound design can still fail to
   realize its own documented intent in the actual wiring. The new
   architecture must verify intent against wiring, not just against
   the design doc.
6. A system can accumulate a large amount of legitimate, working
   infrastructure (18 packages, thousands of tests) and still be
   carrying dead weight (a fully orphaned legacy codebase, a
   validation script that doesn't validate the current system) that
   nobody has explicit reason to challenge until someone asks. Building
   the new architecture from scratch is the right response to that,
   provided each surviving concept is re-earned deliberately rather than
   carried over by default — which is exactly the discipline this
   report and the next phase are structured to apply.

---

## New Phantom architecture

Seven components, matching your specified shape. Every subsystem below
states why it exists, what problem it solves, why it deserves to exist,
and why its responsibility is not duplicated anywhere else in the
system — this is the structural answer to "one authority per decision."

### 1. `PhantomBridgeEA.mq5` (MQL5, terminal-side) + `bridge/` (Python-side counterpart)

**Why it exists:** something has to physically place, modify, and close
orders on the MT5 terminal, and something has to carry validated
commands and telemetry between that terminal and the Python decision
authority. **What problem it solves:** MT5 has no native way to run
Python decision logic inside the terminal process; this component is
the sole physical actuator and the sole transport. **Why it deserves to
exist:** without it, no decision made anywhere else in the system can
ever become a real order. **Why it's not duplicated:** every other
component either produces a decision that flows *into* this component,
or observes state *reported by* this component — no other component
ever talks to the broker/terminal directly, and this component never
makes a trading decision of its own (it only executes what it's told,
after enforcing the security/execution invariants from §5-7 above).

### 2. `scanner/` (Scanner + Scoring, one component per your explicit instruction)

**Why it exists:** every trading decision needs a factual read of
current market structure and a normalized confidence measure for
whatever the Strategy Engine proposes. **What problem it solves:**
without a single place that computes "what is the market actually
doing right now" and "how strong is this specific signal," every
strategy would have to redo that work itself, guaranteeing
inconsistent, duplicated indicator math. **Why it deserves to exist:**
market structure and confidence scoring are read-only, factual
computations completely independent of *which* strategy later uses
them — merging them (per your instruction) keeps one authority for
"observe the market" instead of splitting it across two components that
would otherwise need to agree on shared state. **Why it's not
duplicated:** the Strategy Engine consumes this component's output, it
never recomputes indicators or regime state itself; the Risk Engine
consumes volatility/regime classification from here rather than
deriving its own.

### 3. `strategy/` (Strategy Engine)

**Why it exists:** something has to translate "the market looks like
X" into "here is a specific, named trade idea, in this direction, at
this entry concept." **What problem it solves:** without a dedicated
component, trade-idea generation would either live inside the Scanner
(conflating observation with opinion) or inside the Risk Engine
(conflating opinion with sizing/approval) — both wrong authorities for
that responsibility. **Why it deserves to exist:** trade-idea
generation is a genuinely distinct concern from market observation and
from risk approval, and keeping it separate is what makes "playbooks
confirm each other but never decide/size/execute" enforceable as a
structural rule rather than a convention. **Why it's not duplicated:**
every strategy/playbook here is independently written against the same
Scanner output; no strategy computes its own indicators or its own risk
sizing — those responsibilities belong to components 2 and 4
respectively.

### 4. `risk/` (Risk Engine — position sizing, statistical risk, exposure, portfolio limits, drawdown protection)

**Why it exists:** a candidate trade idea is not yet a trade — something
has to decide how much capital it deserves, whether it fits within
account-wide exposure/drawdown limits, and whether the account's
statistical risk profile supports it at all. **What problem it solves:**
without one authority for this, sizing/exposure/drawdown decisions
would be scattered across whatever component happened to touch account
state, exactly the "conflicting risk rules" failure mode this whole
redesign is meant to eliminate. **Why it deserves to exist:** risk
decisions (how much, whether at all, when to hard-stop) are the most
consequence-bearing decisions in the entire system and need one place
that can be audited, tested, and trusted in isolation. **Why it's not
duplicated:** the kill-switch/lockout authority (§5 above) lives
exclusively here; every other component that needs to know "is trading
currently allowed" reads this component's decision, none recomputes it.
Statistical risk (Monte Carlo, Kelly, VaR/CVaR-style analysis) lives
inside this same component per your explicit grouping, as an internal
capability feeding the same sizing/exposure decisions — not a separate
authority that could disagree with it.

### 5. `intelligence/` (news, trade memory, RAG, AI explanations, learning — advisory only)

**Why it exists:** there is real value in explaining *why* a decision
was made, remembering past trades, and surfacing relevant news/context
— but none of that is itself a trading decision. **What problem it
solves:** without a structurally separate, clearly-bounded component
for this, "helpful AI features" tend to creep into actually influencing
trades — exactly the failure mode your instruction explicitly forbids
("never allowed to generate trades"). **Why it deserves to exist:**
explainability, memory, and research are genuinely useful and distinct
from the decision pipeline itself; keeping them in their own component
makes "advisory only" enforceable as a boundary (this component can be
constructed to have zero import path into the strategy/risk/bridge
components' decision-making functions) rather than just a stated
intention. **Why it's not duplicated:** this is the only component that
reads history/news/context for explanatory purposes; nothing else in
the system re-implements memory or explanation, and this component
never writes back into any decision path — it only ever produces
observations, summaries, and read-only advisory output.

### 6. `watchdog/` (health monitoring, auto recovery, emergency stop, logging)

**Why it exists:** the system needs one place responsible for noticing
when something is broken (a stale connection, a hung process, a missing
heartbeat) and for the *operational* (not trading-decision) emergency
stop capability. **What problem it solves:** without a dedicated
component, health/recovery concerns get bolted onto whatever component
happens to notice a problem first, which is exactly how you end up with
two independent, possibly-disagreeing kill-switch mechanisms (a
specific failure mode this redesign has already found and must not
reintroduce). **Why it deserves to exist:** infrastructure health and
recovery is a different kind of concern from trading risk — one is
"is the system itself working," the other is "should this specific
trade happen" — conflating them was exactly the ambiguity the internal
audit had to carefully untangle for the existing system's kill-switch
layering. **Why it's not duplicated:** the Risk Engine owns the
trading-decision kill-switch (§4); Watchdog owns operational health and
an *operator-facing* emergency stop distinct in scope from the Risk
Engine's decision authority — the two must never be merged into one
undifferentiated "stop everything" mechanism, and neither may silently
recompute the other's state.

### 7. `config/` (single configuration source)

**Why it exists:** every other component needs configuration values
(thresholds, credentials, intervals, symbol lists), and there must be
exactly one place those values are defined and loaded from. **What
problem it solves:** scattered, per-component configuration is how you
end up with two components disagreeing about the same nominal setting
(a documented risk already flagged in the external bridge audits'
lesson about isolation-scope drift). **Why it deserves to exist:** a
single configuration source is what makes "one authority per decision"
possible to verify — if every component reads from the same place, a
misconfiguration is visible in one location, not scattered across
6 different `config.py` files that each need to independently agree.
**Why it's not duplicated:** no other component defines its own
configuration dataclass independently; every other component consumes
values sourced from this one component.

---

## Final folder structure

```
phantom/
├── config/
│   ├── __init__.py
│   └── settings.py
├── bridge/
│   ├── __init__.py
│   ├── models.py
│   ├── validation.py
│   ├── command_queue.py
│   └── server.py
├── scanner/
│   ├── __init__.py
│   ├── models.py
│   ├── structure.py
│   ├── regime.py
│   ├── scoring.py
│   └── engine.py
├── strategy/
│   ├── __init__.py
│   ├── models.py
│   ├── playbook.py
│   ├── playbooks/
│   │   └── (one file per strategy, added deliberately, none yet)
│   ├── session.py
│   ├── entry_validation.py
│   └── engine.py
├── risk/
│   ├── __init__.py
│   ├── models.py
│   ├── sizing.py
│   ├── statistical.py
│   ├── exposure.py
│   ├── drawdown.py
│   └── engine.py
├── intelligence/
│   ├── __init__.py
│   ├── news.py
│   ├── memory.py
│   ├── rag.py
│   ├── explain.py
│   └── engine.py
├── watchdog/
│   ├── __init__.py
│   ├── health.py
│   ├── recovery.py
│   ├── emergency_stop.py
│   └── engine.py
└── orchestrator.py

mt5/
├── PhantomBridgeEA.mq5
└── PhantomBridgeEA.set

scripts/
└── check_architecture.py

tests/
└── phantom/
    └── (mirrors the package structure above, one test module per source file)
```

This is 7 Python packages (matching your 7-component list exactly, with
`bridge/` as the Python-side half of component 1) plus one orchestrator
file, plus the single MQL5 EA file, plus a boundary-check script, plus
tests. No `phantom_pipeline/`, no legacy `phantom/`, no
`phantom_institutional.py`, no `DEPLOYMENT_PACKAGE/` snapshot mechanism
carried over as-is.

## Final file list and responsibility of every file

| File | Responsibility |
|---|---|
| `config/settings.py` | The single source of every configuration value every other component reads; no other file defines its own config dataclass |
| `bridge/models.py` | Wire-message types (heartbeat, account state, tick, bar, position, command, execution report, error) |
| `bridge/validation.py` | Auth, schema, isolation-scope, staleness, and idempotency checks on every inbound message — the security invariants from §5 |
| `bridge/command_queue.py` | The single relay chokepoint between a validated, approved command and the EA picking it up — idempotent by command ID, fail-closed |
| `bridge/server.py` | The Python-side endpoint set the EA talks to; never itself decides anything, only validates, relays, and reports |
| `scanner/models.py` | Structural/regime/scoring data types |
| `scanner/structure.py` | Market structure computation (the factual "what is the market doing" read) |
| `scanner/regime.py` | Regime/volatility/trend classification, feeding both Strategy Engine and Risk Engine |
| `scanner/scoring.py` | Confidence scoring for whatever the Strategy Engine proposes — merged with Scanner per your instruction |
| `scanner/engine.py` | Orchestrates structure + regime + scoring into one observation per evaluation cycle |
| `strategy/models.py` | Candidate-trade and playbook data types |
| `strategy/playbook.py` | The playbook interface every strategy implements — confirmation-layer only, never decides/sizes/executes |
| `strategy/playbooks/*.py` | One file per strategy — added deliberately, each independently justified, none inherited by default |
| `strategy/session.py` | Session-window logic |
| `strategy/entry_validation.py` | Entry-condition validation before a candidate is handed to the Risk Engine |
| `strategy/engine.py` | Orchestrates playbook evaluation against Scanner output |
| `risk/models.py` | Risk-decision data types |
| `risk/sizing.py` | Position sizing |
| `risk/statistical.py` | Monte Carlo / Kelly / VaR-CVaR-style statistical risk, advisory to sizing, never a second authority |
| `risk/exposure.py` | Correlation, currency, and portfolio exposure limits |
| `risk/drawdown.py` | Drawdown protection and the one durable kill-switch/lockout authority |
| `risk/engine.py` | Orchestrates sizing + exposure + drawdown into one risk decision per candidate |
| `intelligence/news.py` | News/calendar context, read-only |
| `intelligence/memory.py` | Trade memory/journal, read-only |
| `intelligence/rag.py` | Retrieval-augmented context for explanations, read-only |
| `intelligence/explain.py` | Human-readable explanation of a decision already made elsewhere |
| `intelligence/engine.py` | Orchestrates the above; structurally has no import path into strategy/risk/bridge decision functions |
| `watchdog/health.py` | Health-check detection (stale heartbeat, hung process, dead connection) |
| `watchdog/recovery.py` | Automated recovery actions scoped to infrastructure, never to trading decisions |
| `watchdog/emergency_stop.py` | The operational, operator-facing emergency stop — distinct from and never merged with the Risk Engine's kill-switch |
| `watchdog/engine.py` | Orchestrates health + recovery + emergency stop |
| `orchestrator.py` | The single wiring point: Scanner → Strategy → Risk → Bridge, with Watchdog observing everything and Intelligence advisory alongside, all fed by Config |
| `mt5/PhantomBridgeEA.mq5` | The only MQL5 file — order/position management and communication with `bridge/server.py`, enforcing the execution invariants from §7 |
| `scripts/check_architecture.py` | Verifies the "one authority per decision" boundary rules hold (no package imports another's private internals, no cross-cutting component gains decision authority) |

## Complete communication flow

1. EA sends heartbeat, account state, tick, and bar telemetry to
   `bridge/server.py`, validated by `bridge/validation.py` on arrival.
2. `orchestrator.py` reads validated telemetry, feeds it to `scanner/engine.py`.
3. When `risk/engine.py` approves a candidate, the approved command is
   handed to `bridge/command_queue.py`, which assigns/tracks the
   idempotent command ID.
4. The EA polls the command queue, receives only already-approved,
   validated commands, executes them, and reports the real
   post-execution result back to `bridge/server.py`.
5. `bridge/command_queue.py` records the result exactly once per command
   ID; a duplicate report is a no-op.
6. If the EA misses its heartbeat window, or the server misses expected
   contact, both sides independently move to a fail-closed state —
   neither trusts the other to remember to time out.

## Complete execution flow

1. `strategy/engine.py` proposes a candidate from `scanner/engine.py`'s
   output — a factual observation plus a proposed direction/entry
   concept, never a size or an execution instruction.
2. `risk/engine.py` sizes it, checks exposure/drawdown/statistical
   limits, and either approves (with a size) or rejects (with a named
   reason) — this is the only point sizing happens.
3. An approved decision goes to `bridge/command_queue.py` as a single,
   idempotent command.
4. The EA (`PhantomBridgeEA.mq5`) is the only code that ever calls the
   broker's order-placement primitive, and only ever for a command it
   received through the queue — never generating, sizing, or deciding
   anything itself.
5. Execution result flows back through the same command ID, recorded
   once, and observable by `watchdog/engine.py` and `intelligence/engine.py`
   for health-monitoring and explanation purposes respectively — neither
   of which can alter the outcome.

## Complete risk flow

1. `scanner/engine.py`'s regime/volatility classification feeds
   `risk/engine.py` directly — Risk Engine never derives its own
   volatility measure.
2. `risk/sizing.py` computes a position size from account state and the
   candidate's characteristics.
3. `risk/statistical.py` provides advisory input (e.g., a Kelly-derived
   sizing recommendation, a Monte-Carlo-derived drawdown expectation)
   that `risk/sizing.py` may use as an input, but statistical risk never
   itself approves or rejects a trade — it only ever informs the one
   sizing authority.
4. `risk/exposure.py` checks the proposed size against portfolio/
   correlation/currency limits.
5. `risk/drawdown.py` checks account-wide drawdown state and owns the
   one kill-switch/lockout authority; if triggered, every other check
   above becomes moot — no trade proceeds regardless of what sizing or
   exposure would otherwise allow.
6. The resulting risk decision (approved-with-size, or rejected-with-reason)
   is the only output `risk/engine.py` produces; nothing downstream
   recomputes any part of it.

## Complete data flow

1. Market telemetry: EA → `bridge/server.py` → `scanner/engine.py`.
2. Observation: `scanner/engine.py` → `strategy/engine.py` (candidate
   generation) and → `risk/engine.py` (regime/volatility context).
3. Decision: `strategy/engine.py` → `risk/engine.py` → `bridge/command_queue.py` → EA.
4. Outcome: EA → `bridge/server.py` → `bridge/command_queue.py` (recorded)
   → `watchdog/engine.py` (health signal) and → `intelligence/engine.py`
   (advisory memory/explanation, read-only, no path back into the
   decision flow).
5. Configuration: `config/settings.py` → every component above, directly;
   no component derives configuration from another component.

---

## Design Principles

- **One responsibility per file.**
- **One authority per decision** — exactly one component ever decides
  direction, one ever sizes, one ever executes, one ever owns the
  kill-switch.
- **Fail closed by default** — silence from either side of any channel
  is treated as "stop," never as "continue."
- **Security first** — authenticate every inbound channel, validate
  before acknowledging, never trust a schema field that isn't provably
  enforced.
- **Deterministic trading** — the same inputs produce the same decision;
  advisory/statistical components never introduce nondeterminism into
  the decision path.
- **Original implementation only** — every reference repository is
  studied for ideas, never copied; every adopted concept is
  reimplemented from first principles.
- **No GPL code** — nothing under a copyleft license is ever vendored or
  adapted into this codebase.
- **No duplicate logic** — no two components ever independently
  recompute the same fact or make the same class of decision.
- **No unnecessary abstraction** — a package exists because it holds a
  genuinely distinct responsibility, not because symmetry or
  future-proofing suggested it should.
- **Simplicity over feature count** — seven components, deliberately,
  not eighteen; every additional file must earn its place the same way
  every additional component did.

---

**Stopping here, per your instruction.** This is a design proposal
only. Waiting for your approval before any implementation begins, and
before continuing the Repository Research Protocol (repository 3 of 5,
`backtrader`, remains unapproved and unstarted).

# Local Filesystem Execution Bridge — Contract

**Status:** **PHASE 2 — IMPLEMENTED (transport only).** The deterministic
filesystem transport is implemented in `forex_swing_orb/bridge/` (single source of
truth). **No execution, no MT5, no broker, no networking, no background service.**
The consumer side is provided as an **interface + validation-only processor**; the
actual execution decision is an injected hook that is out of scope for Phase 2.
**Phase placement:** Phase 1 (strategy engine) is complete and accepted; Phase 2
implements only the bridge; MT5/broker execution is a later phase.
**Related docs:** `docs/FOREX_SWING_ORB_SPEC.md` (frozen strategy spec — Execution
Boundary §0.2, Trade Instruction Contract §8, pipeline reason codes §14);
`docs/TITAN_COMPLIANCE_ENGINE_REVIEW.md`; `docs/VIBE_TRADING_PHASE0_AUDIT.md` (§H
integration map).

---

## 0. No-networking invariant (NORMATIVE — the entire premise)

The bridge is a **local-filesystem-only** handoff. It uses **exclusively** local
filesystem operations: create, write, `flush`/`fsync`, `rename`, `read`,
`unlink`, `stat`, directory scan. It performs an **air-gapped** transfer between
the producer (Vibe-Trading) and the consumer (Titan/MT5) that share a filesystem.

**Explicitly forbidden — none of these may appear in the design or implementation
of the bridge:** HTTP(S), localhost, TCP/UDP sockets, IP addresses, ports,
WinINet, `WebRequest`, WebSockets, named-pipe/loopback-as-network, RPC, message
queues, or any inter-process communication that is not a file on the configured
filesystem. Producer and consumer **never** talk to each other directly; they
communicate **only** by atomically appearing/consuming files in the directories
below.

---

## 1. Architectural placement

```
Vibe-Trading SignalEngine
  → versioned Trade Instruction (§3)
  → local filesystem OUTBOX            (producer writes; §5 atomic)
  → Titan/MT5 compliance + execution adapter   (consumer claims + validates + executes; §6–§8)
  → broker (MT5 terminal)
  → local filesystem INBOX (results)   (consumer writes; §9 atomic)
  → Vibe-Trading audit + reconciliation (producer/analytics reads results)
```

The **SignalEngine remains independent of MT5 and execution** (frozen spec §0.2):
it only writes an instruction file into the outbox and later reads result files
from the inbox for analytics/audit. It never reads broker/account state and never
imports execution code. The bridge is the **sole** coupling between the two sides,
and that coupling is a directory of files.

---

## 2. Phase boundary

- **Current task:** document the filesystem bridge **contract only**.
- **Do NOT implement it during Swing-ORB Phase 1.**
- **Phase 1** (Swing-ORB) is limited to deterministic signal generation,
  qualification, tests, and audit output. Phase 1 may *emit* a logical instruction
  object (frozen spec §8) but does **not** write to any bridge, does **not**
  create bridge directories, and does **not** depend on this contract at runtime.
- **Bridge implementation begins only after Phase 1 acceptance**, as its own phase
  (owned per §13). Until then this document is a target contract, not live code.

---

## 2.1 Phase 2 implementation scope & reconciliation (NORMATIVE)

Phase 2 implements the **transport** only. The following reconcile the design
contract (written pre-implementation) with what the bridge actually does now:

- **Validation subset (of §7).** The bridge performs the transport-level checks it
  can prove from the file + ledger: (1) readable/valid JSON, (2) supported
  `schema_version`, (3) `integrity_digest`, (4) required fields present/typed,
  (4b) known `strategy_version`, (5) `signal_id` not previously processed (dedup),
  (6) not expired, (6b) `generated_timestamp` not implausibly in the future,
  (7) `symbol` in canonical `[A-Z]{6}.FX` form (format only — no broker mapping),
  (8) structural direction/prices (LONG/SHORT; finite/positive; stop/target on the
  correct sides; RR sane). **Steps 9–15 of §7 (market/account freshness, news
  re-validation, Titan compliance, exposure/spread/kill-switch, execution) are
  DOWNSTREAM** (future execution layer) and are **not** implemented or simulated
  by the bridge. After the bridge's checks pass, control is handed to an injected
  **decision hook**; the Phase-2 default hook is *validation-only* and returns
  `ACCEPTED` **without any execution**.
- **Result states (reconciles §9).** The bridge itself emits
  `ACCEPTED` · `REJECTED` · `EXPIRED` · `DUPLICATE` · `FAILED` · `ERROR`.
  `EXECUTED` / `EXECUTION_FAILED` are **reserved for the downstream execution
  layer** and are never emitted by the transport. Corrupt/unreadable/oversized
  files are a **file disposition** (moved to `quarantine/`) recorded in the audit
  log with an `ERROR` outcome; because an unparseable file has no `signal_id`, no
  keyed result file is written for it.
- **Determinism.** All timestamps are **inputs** (an explicit `now` is passed in),
  so `result_id`, audit lines, and outcomes are pure functions of inputs — no
  wall-clock or RNG in bridge logic. There are **no polling loops**: a scan+claim
  is a single pass the caller invokes; the bridge never waits/sleeps.

## 2.2 Phase-2 correction addendum (NORMATIVE — acceptance-review fixes)

Implemented after the Phase-2 acceptance review, closing invariants already
stated in §8/§9/§10:

- **Exactly one terminal result (§9, F-C).** `result_id` is deterministic on
  `(signal_id, terminal_state)` only. Recovery **adopts** an existing terminal
  result (rebuilding the ledger from it) instead of minting a second, and does
  not re-invoke the hook. Terminal writes order result → ledger → archive so any
  crash window is recoverable to a single result.
- **Dedup survives ledger loss (§8, F-D).** One shared seen-resolver treats a
  `signal_id` as seen from the ledger **or** on-disk evidence (`inbox/results/`,
  `archive/accepted|rejected/`, `outbox/claimed/`) and repairs the ledger from
  disk. Conflicting accepted/rejected evidence for one id **fails closed**
  (quarantine).
- **No blind resubmit (§10, F-S).** The decision hook declares a posture
  (`VALIDATION_ONLY` / `IDEMPOTENT` / `NON_IDEMPOTENT_EXECUTION`). Reconciliation
  re-processes a non-terminal claimed item only for a re-runnable posture; under
  the execution posture it marks the item `RECONCILIATION_REQUIRED` and never
  re-invokes the hook. (No real execution hook is attached in Phase 2.)
- **Exclusive claim (F-A):** claim uses `link`+`unlink` and refuses (never
  overwrites) an existing `claimed/<signal_id>`. **Durability (F-1):** first
  ledger/audit create fsyncs file + directory. **Move auditability (F-2):** a
  failed move emits `E_MOVE` and fails closed. **Safe read (F-3):** `O_NOFOLLOW`
  + descriptor `fstat` reduce the TOCTOU window.

## 3. Trade Instruction (on-disk record)

The on-disk instruction is the **frozen versioned Trade Instruction Contract**
(spec §8) serialized as strict JSON, plus transport/integrity fields. Each
instruction file must include **at least**:

| Field | Notes |
|---|---|
| `schema_version` | Instruction schema version (integer). Consumer supports an explicit allow-list (§7 step 2). |
| `signal_id` | Deterministic content hash (spec §8); the primary key everywhere. |
| `strategy_id` | Stable strategy identifier (e.g. `swing_orb`), distinct from `strategy_version`. |
| `strategy_version` | e.g. `swing_orb.v1.2.0`. |
| `symbol` | Canonical `EURUSD.FX` (never a raw `/`-bearing symbol; §4). |
| `direction` | `LONG` / `SHORT`. |
| `entry_price` | float. |
| `stop_loss` | float. |
| `take_profit` | float. |
| `risk_fraction` | e.g. `0.0025` (0.25%); the producer's intended per-trade risk. |
| `generated_timestamp` | UTC ISO-8601. |
| `expiration_timestamp` | UTC ISO-8601 (spec §8.2). |
| `evidence_summary` | Structured decision trail (spec §8.1). |
| `news_eligibility` | Structured news-filter result (spec §12): pass/deny + events/provenance consulted. |
| `integrity_digest` | `sha256` (hex) over the **canonical** serialization of all other fields (see §3.1). Also referred to as the checksum. |

**Schema evolution note (unresolved decision, §15-D1):** three of the required
fields — `strategy_id`, `risk_fraction`, `news_eligibility` — are today either
derivable or nested inside the frozen schema-v1 instruction (spec §8). Promoting
them to first-class instruction fields, plus adding `integrity_digest`, is an
instruction **schema bump to v2** to be applied **when the bridge phase begins**.
The frozen strategy spec stays at instruction schema v1 for Phase 1; this document
defines the v2 target so the two can be reconciled deliberately, not silently.

### 3.1 Integrity digest (deterministic)

`integrity_digest = sha256(canonical_json(instruction_without_digest))`, where
`canonical_json` sorts keys, uses fixed number formatting, UTF-8, and no
insignificant whitespace. The digest is computed by the producer over every field
except the digest itself, and re-computed and compared by the consumer (§7 step 3).
It detects truncation/corruption independent of the atomic-rename guarantee.

---

## 4. File naming (deterministic, filesystem-safe)

- Filenames derive **only** from `signal_id` (a 16-hex-char content hash, spec §8)
  and, for results, `result_id` — both are restricted to `[0-9a-f_-]`, so they are
  filesystem-safe on all target platforms.
- **Instruction file:** `outbox/pending/<signal_id>.json`.
- **Result file:** `inbox/results/<signal_id>.<result_id>.json`.
- **Raw symbols are NEVER placed in filenames.** The canonical `EURUSD.FX` (and
  emphatically any `/`-bearing form) appears only **inside** the file as the
  `symbol` field, never in a path component (avoids the `/`-in-name hazard,
  audit §F).
- No spaces, no uppercase-dependence, no reserved device names; extension is
  `.json`. Temporary files use a leading-dot + `.tmp` suffix (§5).

---

## 5. Atomic write semantics

**Producer (Vibe-Trading) — write an instruction:**
1. Serialize the **complete** instruction (incl. `integrity_digest`) to a
   temporary file **in the same directory / filesystem** as the destination:
   `outbox/pending/.<signal_id>.json.tmp` (same-mount → rename is atomic).
2. `flush()` then `fsync()` the file where supported; `fsync()` the containing
   directory where supported (so the rename is durable).
3. **Atomically `rename`** the temp file to `outbox/pending/<signal_id>.json`.
4. **Never expose a partially written instruction** — consumers only ever see the
   final name, which appears atomically and complete. (A crash mid-write leaves
   only a `.tmp` file, which consumers ignore, §11.)

**Consumer (Titan/MT5) — claim an instruction:**
- **Atomically `rename`** `outbox/pending/<signal_id>.json` →
  `outbox/claimed/<signal_id>.json` **before** any processing. The successful
  rename **is** the claim. Processing only ever reads from `outbox/claimed/`.
- A file still present in `outbox/pending/` is unclaimed; a file in
  `outbox/claimed/` is owned by exactly one consumer.

All result writes (§9) use the same **temp-write + `fsync` + atomic-rename**
pattern into `inbox/results/`.

---

## 6. Directory layout (beneath one configurable bridge root)

`bridge_root` is a single configurable path (§14 security). Beneath it:

| Directory | Owner writes | Purpose |
|---|---|---|
| `outbox/pending/` | Producer | Instructions ready to be claimed. |
| `outbox/claimed/` | Consumer | Instructions claimed for processing (in-flight). |
| `inbox/results/` | Consumer | Exactly one terminal result per claimed instruction (§9). |
| `archive/accepted/` | Consumer | Terminally accepted/executed instructions moved out of `claimed/`. |
| `archive/rejected/` | Consumer | Terminally rejected/expired/quarantined-origin instructions. |
| `quarantine/` | Consumer | Malformed/oversized/unsafe files isolated for inspection (§11). |
| `health/` | Both | Liveness/heartbeat + persistent dedup/reconciliation state (files only, §8/§10/§11). |

All directories live on **one filesystem** so every cross-directory `rename`
(pending→claimed, claimed→archive, tmp→final) is atomic.

---

## 7. Validation order (deterministic; first failure ⇒ NO TRADE)

The consumer applies these checks in this **fixed order**; the first failure
produces **no trade** and a terminal result (§9) with the mapped `reason_code`.
No later check can override an earlier failure.

1. **Readable & valid serialization** — file parses as strict JSON (else `E_SERDE`).
2. **Supported schema version** — `schema_version` in the consumer allow-list
   (else `E_SCHEMA`).
3. **Integrity/checksum** — recomputed `integrity_digest` matches (else `E_INTEGRITY`).
4. **Required fields present** — all §3 fields present and typed (else `E_FIELDS`).
5. **`signal_id` not previously processed** — dedup check (§8) (else `E_DUP`).
6. **Not expired** — now ≤ `expiration_timestamp` (else `E_EXPIRED`).
7. **Symbol mapping valid** — `symbol` maps to a known broker symbol (else `E_SYMBOL`).
8. **Direction & prices structurally valid** — direction ∈ {LONG,SHORT}; prices
   finite & positive; stop/target on the correct sides of entry; implied RR sane
   (else `E_STRUCT`).
9. **Market/account data fresh** — required snapshots present & not stale
   (else `E_STALE`).
10. **News eligibility valid** — `news_eligibility` present, fresh, non-conflicting;
    no active high-impact lockout (else `E_NEWS`).
11. **Titan compliance checks** — the Titan Compliance Engine gate
    (`docs/TITAN_COMPLIANCE_ENGINE_REVIEW.md`) (else `E_COMPLIANCE`).
12. **Position & exposure limits** — one-position/symbol, exposure/leverage caps
    (else `E_LIMITS`).
13. **Spread & broker constraints** — live spread within bound; broker
    tradability (else `E_SPREAD`).
14. **Kill-switch & trading authorization** — halt not tripped; authorized
    (else `E_KILL`).
15. **Execution** — place the order; outcome recorded as `EXECUTED` or
    `EXECUTION_FAILED` (§9).

Reason codes reuse the strategy pipeline codes where they align (spec §14) and add
the bridge-specific codes above. Every outcome is auditable.

---

## 8. Deduplication

- Titan/MT5 must **reject** any `signal_id` that has already been **claimed,
  accepted, rejected, executed, or recorded in persistent deduplication state**
  (validation step 5 → `E_DUP`).
- **Persistent dedup state** lives as files under `health/` (append-only,
  `fsync`-ed ledger keyed by `signal_id` with its terminal state and timestamps),
  cross-checked against on-disk evidence (`outbox/claimed/`, `archive/*`,
  `inbox/results/`).
- **Dedup must survive process and terminal restarts** — the ledger is durable and
  is the authority; the content-derived `signal_id` (spec §8) makes dedup exact
  (identical instruction ⇒ identical id).
- The dedup insert for a `signal_id` is committed **atomically with the claim/
  terminal transition**, so a crash cannot leave a half-recorded id (§11).

---

## 9. Acknowledgement & result contract

For **every claimed instruction**, the consumer writes **exactly one** terminal
result file (`inbox/results/<signal_id>.<result_id>.json`, temp-write + `fsync` +
atomic-rename per §5). Each result contains at least:

- `signal_id`
- `result_id` (deterministic, e.g. `sha256(signal_id|processed_timestamp|status)[:16]`)
- `status` ∈ { **ACCEPTED**, **REJECTED**, **EXECUTED**, **EXECUTION_FAILED**,
  **EXPIRED**, **QUARANTINED** }
- `reason_code` (§7 codes) and `reason_detail` (structured, human-readable, no secrets)
- `received_timestamp`, `processed_timestamp` (UTC ISO-8601)
- `broker_order_id` — when applicable
- `requested_price`, `filled_price`
- `requested_volume`, `filled_volume`
- `slippage`
- `stop_loss`, `take_profit` (as sent to broker)
- `compliance_decision` (the §11 Titan gate outcome + ordered check results)
- `execution_error` — when applicable

Exactly-one-terminal-result is invariant: a claimed instruction always ends in a
single result and is then moved from `outbox/claimed/` to `archive/accepted/` or
`archive/rejected/`. Vibe-Trading ingests results from `inbox/results/` for
analytics/audit only (it never mutates them).

---

## 10. Failure & recovery (deterministic)

- **Malformed files → `quarantine/`** (unparseable, oversized, wrong shape, unsafe
  path) with a `QUARANTINED` result; never processed further.
- **Expired instructions are never executed** — step 6 denies with `EXPIRED`.
- **Files left in `outbox/claimed/` after a restart are reconciled before any
  retry** — the consumer, on startup, inspects each claimed file, checks the dedup
  ledger and (where a broker outcome may exist) the MT5 **account/order state**,
  and only then decides ACCEPTED/REJECTED/EXECUTED/EXECUTION_FAILED/EXPIRED.
- **Uncertain broker outcomes are reconciled against MT5 account/order state** (by
  `signal_id`/`broker_order_id` correlation) — **an uncertain execution is never
  blindly resubmitted.**
- **Missing state or failed reconciliation ⇒ no trade** (fail-closed): if the
  ledger/broker state cannot be read or is contradictory, the instruction is
  denied, not executed.
- **Every recovery action is auditable** — each reconciliation writes a structured
  audit record (and, for a terminal transition, the single result file, §9).

---

## 11. Security

- **`bridge_root` is configurable** (single path; no other location is used).
- **Narrowest filesystem permissions available** — private directories and files
  (e.g. `0700` dirs / `0600` files on POSIX; equivalent restrictive ACLs on
  Windows). Producer and consumer run under identities with only the access they
  need.
- **Never store broker credentials or API keys inside instruction/result files** —
  instruction files are strategy/trade data only.
- **Reject symbolic links and path escape** — resolve real paths and verify every
  file is a **regular file** strictly under `bridge_root`; refuse symlinks
  (`O_NOFOLLOW`/`lstat` where available) and any `..`/absolute path escaping the
  root. Files are addressed only by `<signal_id>`-derived basenames (§4).
- **Enforce a maximum file size** — files larger than `max_instruction_bytes`
  (and `max_result_bytes`) are quarantined unread past the cap.
- **Strict schema; reject unknown critical fields** — parse against an explicit
  schema; unknown fields in the critical set are rejected (`E_FIELDS`/`E_SCHEMA`),
  not ignored.
- **Never execute code contained in a file** — files are **inert JSON data**. No
  `eval`, `exec`, `pickle`, dynamic import, or format capable of code execution is
  used to read them.

---

## 12. Test requirements (future bridge phase — documented now, run then)

Tests to specify and later run when the bridge phase begins:

- **Atomic-write visibility** — a reader never sees a file until it is complete.
- **Partial-file resistance** — an interrupted write leaves only a `.tmp`, ignored.
- **Duplicate signal rejection** — a re-presented `signal_id` is denied (`E_DUP`).
- **Restart-persistent deduplication** — dedup holds across process/terminal
  restart.
- **Expired signal rejection** — past-`expiration_timestamp` never executes.
- **Malformed instruction quarantine** — bad JSON/shape → `quarantine/` +
  `QUARANTINED`.
- **Unsupported schema rejection** — out-of-allow-list `schema_version` → `E_SCHEMA`.
- **Checksum failure** — tampered/truncated payload → `E_INTEGRITY`.
- **Atomic claiming with two competing consumers** — exactly one claims; the other
  gets `ENOENT` and skips; no double-processing.
- **Claimed-file crash recovery** — a file stranded in `claimed/` is reconciled
  before any retry.
- **Uncertain-order reconciliation** — ambiguous broker outcome resolved against
  MT5 state; no blind resubmit.
- **Acknowledgement generation for every terminal outcome** — exactly one result
  per claimed instruction, for each status.
- **Filesystem-safe symbol naming** — no `/`-bearing or raw symbol ever appears in
  a filename.
- **No use of networking or WinINet** — a static/behavioral check asserts the
  bridge performs only filesystem operations (no sockets/HTTP/WinINet/WebRequest).
- **No duplicate order after restart** — replaying pending/claimed across a restart
  never produces a second broker order for the same `signal_id`.

---

## 13. Ownership

**Titan owns:** instruction ingestion; compliance validation; deduplication;
account and broker checks; execution; acknowledgement (result writing);
reconciliation; kill-switch enforcement.

**Vibe-Trading owns:** strategy qualification; evidence; signal generation;
instruction production (writing to `outbox/pending/`); result ingestion for
analytics and audit (reading `inbox/results/`).

The boundary is the filesystem: Vibe-Trading writes instructions and reads
results; Titan reads instructions and writes results. Neither imports the other's
code across the bridge; neither opens a network connection to the other.

### 13.1 Full-lifecycle reconciliation (FUTURE REQUIREMENT — bridge/execution phase)

**Not implemented in Swing-ORB Phase 1** (Phase 1 is signal generation only; it
never writes to the bridge). This is a forward requirement for the future
bridge/execution phase, recorded here in the downstream execution document:

Every signal that is ever acted on must eventually carry a **complete, auditable
lifecycle**, reconciled end-to-end and keyed by `signal_id`:

1. **signal generated** (SignalEngine → instruction, spec §8)
2. **compliance accepted or rejected** (Titan gate, §7 / Titan review)
3. **order submitted** (to the broker/MT5)
4. **broker accepted or rejected**
5. **order filled, partially filled, cancelled, or expired**
6. **position closed**
7. **final P&L**
8. **exit reason**

The result contract (§9) captures stages 2–5; stages 6–8 require the execution
phase to correlate fills/closes back to the originating `signal_id` and emit a
terminal lifecycle record that Vibe-Trading ingests for analytics/audit. This
belongs to the future bridge/execution phase — **not** to the SignalEngine.

---

## 14. Configuration (bridge phase)

| Param | Meaning |
|---|---|
| `bridge_root` | Single configurable root for all directories (§6). Must be on one filesystem. |
| `schema_version_allowlist` | Instruction schema versions the consumer accepts (§7-2). |
| `max_instruction_bytes` / `max_result_bytes` | File-size caps (§11). |
| `claim_reconcile_on_startup` | Enforce §10 claimed-file reconciliation at start. |
| `dedup_ledger_path` | Durable dedup state under `health/` (§8). |
| `heartbeat_interval` | Producer/consumer liveness marker cadence (file mtime only; no network). |

---

## 15. Unresolved decisions (flagged; none block this documentation step)

- **D1 — RESOLVED (Phase 2): extend, don't bump.** The strategy engine already
  emits `strategy_id`, `risk_fraction`, and `news_eligibility` as first-class
  instruction fields at `schema_version = 1` (spec §8), so no v2 strategy bump is
  needed. `integrity_digest` is a **bridge transport field** added at write time
  and excluded from the digest computation itself (§3.1). The bridge's
  `schema_version_allowlist` default is `{1}`.
- **D2 — Result retention/rotation:** retention policy for `inbox/results/` and
  `archive/*` (size/age-based rotation) is unspecified pending operational input.
- **D3 — Multi-consumer topology:** the claim protocol supports competing
  consumers, but whether more than one Titan consumer is ever run concurrently
  (and any per-symbol affinity) is undecided.
- **D4 — Health/heartbeat semantics:** exact staleness thresholds and what a stale
  producer/consumer heartbeat should trigger (pause vs alert) are deferred to the
  bridge phase (kept file-only per §0).
- **D5 — Cross-platform permission parity:** the exact narrowest-permission model
  on Windows (vs POSIX `0700/0600`) needs confirmation for the deployment target.

# Session Edge Filesystem Execution Bridge (Phase 2 — transport only)

Deterministic, **filesystem-only** transport of trade instructions from the
Session Edge strategy engine (producer) to a future execution layer (consumer).
Implements `docs/FILESYSTEM_EXECUTION_BRIDGE_SPEC.md`. Single source of truth —
no parallel bridge, no duplicate serializers/validators.

**It never executes trades.** No MT5, no broker, no networking, no background
service, no scheduler. Pure Python **stdlib** (`os`, `json`, `hashlib`, `pathlib`,
`datetime`, `re`, `dataclasses`).

## Modules (single responsibility)

| Module | Responsibility |
|---|---|
| `config.py` | `BridgeConfig` (allow-lists, size caps, skew tolerance, symbol pattern). |
| `paths.py` | `bridge_root` layout, dir creation (0700), filesystem-safety (no symlink/escape), name rules. |
| `serialize.py` | Canonical JSON, `integrity_digest`, ISO-8601 helpers, deterministic `result_id`. |
| `contract.py` | Required instruction fields, `ResultState`, `ReasonCode`, result builder. |
| `atomic.py` | temp→flush→fsync→atomic-rename write; atomic claim/move; fsync'd JSONL append. |
| `ledger.py` | Persistent, restart-surviving dedup ledger. |
| `audit.py` | Deterministic append-only audit log. |
| `producer.py` | Write instructions atomically into `outbox/pending/`. |
| `validate.py` | Ordered transport validation pipeline (stop on first failure). |
| `consumer.py` | Atomic claim, validate, write result, archive, quarantine; injected decision hook. |
| `reconcile.py` | Single-pass restart recovery. |

## Directory layout (one `bridge_root`, one filesystem)

```
bridge_root/
  outbox/pending/     producer writes; claimable instructions
  outbox/claimed/     consumer-owned, in-flight
  inbox/results/      exactly one terminal result per claimed instruction
  archive/accepted/   terminally accepted instructions
  archive/rejected/   terminally rejected/expired/duplicate instructions
  quarantine/         corrupt / oversized / unsafe artifacts
  health/             dedup.jsonl (ledger) + audit.jsonl
```

## Serialization

Instructions are the engine's `schema_version = 1` dict (signal_id, strategy_id,
strategy_version, symbol, direction, entry/stop/target, risk_fraction,
generated/expiration timestamps, evidence_summary, news_eligibility) plus the
bridge transport field `integrity_digest = sha256(canonical_json(record_without_digest))`.
`canonical_json` = sorted keys, compact separators, UTF-8, no NaN → byte-stable.
Filenames are hex-only: `outbox/pending/<signal_id>.json`,
`inbox/results/<signal_id>.<result_id>.json`; raw `/`-bearing symbols never appear
in a path.

## Validation pipeline (transport subset, stop on first failure)

schema version → integrity digest → required fields → known strategy → signal_id
form/filename → **dedup** → expiry (`now >= expiration ⇒ EXPIRED`) → future-skew →
symbol format → structural direction/price geometry. Steps 9–15 of the spec
(market/account freshness, news re-validation, Titan compliance, exposure/spread/
kill-switch, execution) are **downstream** and not performed here. On pass, an
injected **decision hook** runs; the Phase-2 default is validation-only →
`ACCEPTED`, no execution.

## Atomic write & claim

Write: temp `.<name>.tmp` in the destination dir → `flush` → `fsync` file → atomic
`os.replace` → `fsync` dir. A crash leaves only a `.tmp` (ignored). Claim: atomic
`os.rename` pending→claimed; the winning rename **is** the claim (no lock files);
a losing racer gets no file and skips.

## Result states

`ACCEPTED` · `REJECTED` · `EXPIRED` · `DUPLICATE` · `FAILED` · `ERROR`.
`EXECUTED`/`EXECUTION_FAILED` are reserved for the downstream execution layer.
Execution-only result fields (broker_order_id, filled_*, slippage, …) are always
`null` here.

## Reconciliation (restart recovery)

Single pass, no polling: delete stray `.tmp`; quarantine bad-named/unsafe files;
for each stranded `claimed/` file — if terminal in the ledger, finish the
interrupted archive move (never re-run); else safely re-process (transport is
idempotent). Dedup ledger is durable and authoritative, so no double-processing
across restarts. Fails closed throughout.

## Determinism

All timestamps are **inputs** (`now` is passed in), so `result_id`, audit lines,
and outcomes are pure functions of inputs — no wall-clock or RNG in logic, no
polling/busy-wait.

## Usage

```python
from forex_swing_orb import bridge
paths, ledger, audit, consumer = bridge.open_bridge("/path/to/bridge_root")
# producer (e.g. from engine.instructions[symbol]):
bridge.write_instructions(paths, instructions, now)
# consumer (transport only — no execution):
sid = consumer.claim_next(now)
result = consumer.process(sid, now)   # -> ACCEPTED (validation-only default hook)
# on startup:
bridge.recover(consumer, now)
```

## Tests

`bridge/tests/` — 34 stdlib-only regression tests (atomic write/claim, dedup,
restart recovery, quarantine, invalid schema/digest/fields/geometry, expiry,
future-skew, corrupt/oversized, multi-consumer race, audit, deterministic
serialization, idempotency, no-networking/no-MT5 static checks) + 1 pandas-gated
engine→producer integration test. Run: `python -m pytest forex_swing_orb/bridge/tests`.

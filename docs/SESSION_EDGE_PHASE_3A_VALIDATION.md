# Session Edge — Phase 3A End-to-End System Validation

**Scope:** validation only. No production features, strategy logic, bridge/EA
behaviour, AI/LLM, Sentinel, deployment, or cloud were added. Failure injection
is done with test-time monkeypatching of the standard library and component
seams — production code is untouched.

**System under test:** Strategy Engine → Filesystem Bridge → Execution Adapter →
Mock MT5 Broker → Acknowledgement → Execution Result → Recovery → Audit.

**Test corpus:** `forex_swing_orb/validation/` — 52 validation tests
(E2E scenarios, restart/crash recovery, failure injection, determinism, load
1k/5k/10k, static boundary), plus the pre-existing 145 engine + bridge + adapter
tests, and the full official Vibe-Trading suite as regression.

---

## 1. Validation architecture

```mermaid
flowchart TD
    E[Strategy Engine\nswing_orb.v1.4.0\n(run_dir/code)] -->|instruction dicts| P[Producer\nwrite_instruction + integrity_digest]
    P -->|outbox/pending| B[(Filesystem Bridge\nsingle source of truth)]
    B -->|exclusive claim| A[Execution Adapter\nExecutionConsumer + EA]
    A -->|ack| K[inbox/acks]
    A -->|OrderSend BUY/SELL + SL/TP\ncomment = signal_id| M[Mock MT5 Broker\n(test double)]
    A -->|one terminal result| R[inbox/results]
    A -->|archive| ARC[archive/accepted|rejected]
    A -->|corrupt/unsafe| Q[quarantine]
    A -->|every action| AU[health/audit.jsonl]
    B -. restart .-> A
    M -. broker truth .-> A
    subgraph Recovery
      A -->|scan claimed + broker query + ledger/archive| RC{reconstruct state}
    end
```

The harness (`validation/harness.py`) wires the **real** components (bridge +
execution adapter + mock terminal) and, for the true end-to-end path, the **real
strategy engine** loaded by file path exactly as Vibe-Trading loads a run-dir
engine. Determinism is guaranteed by injecting `now` and using a fixed broker
ticket counter.

---

## 2. Test matrix

| Area | Cases | Result |
|---|---|---|
| Normal execution | BUY, SELL, multi-symbol (8), sequential (25), simultaneous single-sweep (50) | ✅ |
| Real engine → execution | synthetic ORB signal → EXECUTED end-to-end | ✅ |
| Duplicates | duplicate instruction, duplicate signal_id | ✅ (DUPLICATE, no 2nd order) |
| Validation | expired, digest mismatch, schema mismatch, strategy mismatch, corrupt file, incomplete | ✅ (fail closed) |
| Broker | reject, market-closed, off-quotes, requote, trade-busy, disconnected, invalid symbol/volume | ✅ (EXECUTION_FAILED) |
| Restart | bridge restart, EA restart, both together, orphan claimed | ✅ |
| Recovery | ledger loss, archive-only evidence, quarantine continuation, ticket-map rebuild | ✅ |
| Crash points | during claim, ack, execution, result-write, archive, reconciliation | ✅ |
| Filesystem | permission error, disk full, partial write / power-loss | ✅ (fail closed) |
| Corruption | corrupt claimed file, conflicting terminal evidence | ✅ (quarantine) |
| Determinism | byte-identical artifacts + reason codes + outcomes over two runs | ✅ |
| Load | 1,000 / 5,000 / 10,000 signals | ✅ (exactly-once at every scale) |
| Boundary | no networking / AI / broker-SDK / strategy-in-EA / duplicated logic | ✅ |

---

## 3. Failure matrix

Every injected failure **fails closed**, emits a **deterministic audit** entry,
and **never leaks an order or a torn artifact**.

| Failure | Stage | Behaviour | Reason code | Order placed? | Recovers |
|---|---|---|---|---|---|
| Expired instruction | validate | terminal `EXPIRED` | `E_EXPIRED` | no | n/a |
| Digest mismatch | validate | terminal `REJECTED` | `E_INTEGRITY` | no | n/a |
| Schema mismatch | validate | terminal `REJECTED` | `E_SCHEMA` | no | n/a |
| Strategy mismatch | validate | terminal `REJECTED` | `E_STRATEGY` | no | n/a |
| Incomplete fields | validate | terminal `REJECTED` | `E_FIELDS` | no | n/a |
| Corrupt/unparseable | read | quarantine | `E_SERDE` | no | pipeline continues |
| Conflicting evidence | dedup | quarantine | `E_CONFLICT` | no | pipeline continues |
| Duplicate signal_id | dedup | adopt existing | `E_DUP` → `DUPLICATE` | no | n/a |
| Invalid broker symbol | broker check | `EXECUTION_FAILED` | `X_INVALID_SYMBOL` | no | new signal ok |
| Invalid volume | broker check | `EXECUTION_FAILED` | `X_INVALID_VOLUME` | no | new signal ok |
| Broker reject | order | `EXECUTION_FAILED` | `X_BROKER_REJECT` | no | new signal ok |
| Market closed | order | `EXECUTION_FAILED` | `X_MARKET_CLOSED` | no | new signal ok |
| Off quotes | order | `EXECUTION_FAILED` | `X_OFF_QUOTES` | no | new signal ok |
| Requote | order | `EXECUTION_FAILED` | `X_REQUOTE` | no | new signal ok |
| Trade context busy | order | `EXECUTION_FAILED` | `X_TRADE_BUSY` | no | new signal ok |
| Terminal disconnected | order | `EXECUTION_FAILED` | `X_DISCONNECTED` | no | reconnect + new signal ok |
| FS permission error | write | raises, no artifact | (exception + no file) | no | reprocess after clear |
| FS full (ENOSPC) | write | raises, no artifact | (exception + no file) | no | reprocess after clear |
| Partial write / power-loss | write | only `.tmp`, never visible | — | no | `.tmp` cleaned on recover |

---

## 4. Recovery matrix (restart / crash)

State is reconstructed from the **filesystem bridge + MT5 terminal**, never from
memory. **No duplicate execution, ack, or result is ever produced.**

| Crash point | On-disk state at restart | Recovery decision | 2nd order? |
|---|---|---|---|
| During claim (link done, unlink not) | pending + claimed both present | recover executes claimed once; stray pending re-claim → `DUPLICATE` | no |
| During ack | claimed + ack, no broker position | `RECONCILIATION_REQUIRED` (fail closed) | no |
| During execution | claimed + ack + **broker position** | finalize `EXECUTED` from broker truth (`X_RECONCILE`) | no |
| During result write | claimed + ack + broker position + `.tmp` | clean `.tmp`, finalize from broker truth | no |
| During archive | result + ledger durable, claimed present | adopt terminal evidence, complete archive | no |
| During reconciliation | partial recovery | re-run is idempotent; converges | no |
| Orphan claimed | claimed only | safe first execution | no (first) |
| Ledger lost | archive/result present | resolver rebuilds ledger from disk | no |
| Archive-only evidence | archive present, ledger+result gone | resolver treats as terminal → `DUPLICATE` | no |

**No-double-order is enforced three independent ways:** bridge dedup resolver, a
point-of-execution broker check (`position_by_comment`), and broker-aware
recovery.

Restart reconstruction rebuilds the transient `signal_id → ticket` map from open
broker positions (order comment = `signal_id`); it is fast even at scale
(≈0.05 s for 10,000 positions).

---

## 5. Load-test results (measured)

Full pipeline, one process, fsync-durable writes, mock terminal.

| Signals | Produce (s) | Drain (s) | Throughput (sig/s) | Latency (ms/sig) | Peak mem (MB) | Disk (MB) | Disk/sig (B) | Recover (s) | Dedup lookup (µs) | Scan (s) |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1,000 | 0.89 | 9.85 | 101.5 | 9.85 | 4.32 | 2.14 | 2,140 | 0.005 | 54 | 0.0015 |
| 5,000 | 3.84 | 126.0 | 39.7 | 25.2 | 11.79 | 10.70 | 2,140 | 0.021 | 37 | 0.0078 |
| 10,000 | 8.05 | 466.2 | 21.4 | 46.6 | 25.44 | 21.41 | 2,140 | 0.052 | 39 | 0.0099 |

**Correctness held at every scale:** all N executed, exactly one result each, N
unique broker orders, no duplicates.

**Key finding — super-linear throughput.** Throughput falls (101 → 40 → 21
sig/s) and per-signal latency rises (9.9 → 46.6 ms) as the backlog grows. Cause:
the dedup resolver scans the whole `inbox/results/` directory per signal, and
`claim_next` re-sorts the whole `outbox/pending/` per claim — an O(N²) pattern
over a large single-directory backlog. This is a **performance** property, not a
correctness one, and is comfortably within budget for the strategy's real
cadence (a handful of signals per session). It is a documented scaling risk for
high-volume use (see §9). Memory and disk are linear (~2.6 KB/signal in-flight,
2.14 KB/signal at rest). Restart recovery is sub-100 ms even at 10k.

---

## 6. Determinism verification

Two independent runs with identical instructions and identical injected `now`
(fresh terminals, same fixed ticket counter) produce **byte-identical**:
instructions, acknowledgements, results, archives, dedup ledger, and audit log;
and identical reason codes and terminal outcomes. `result_id`/`ack_id` are
content-addressed (`sha256(signal_id|state)[:16]`) with no wall-clock input.
Proven by `test_determinism.py` (full-tree byte snapshot comparison).

---

## 7. Performance metrics summary

- Execution latency is dominated by durable-write cost (fsync per artifact:
  ack + result + ledger append + dir fsyncs ≈ 4 syncs/signal). At small backlog
  ≈ 10 ms/signal.
- Dedup lookup ≈ 40–54 µs/call; bridge directory scan ≈ 1.5–10 ms at
  1k–10k backlog.
- Restart reconstruction ≈ 5–52 ms for 1k–10k in-terminal positions.
- Memory footprint negligible and linear; the adapter holds only a transient
  `signal_id → ticket` map.

---

## 8. Boundary verification

Static, whole-system (engine + bridge + adapter, `.py` + `.mq5`/`.mqh`):

- **No networking:** no `WebRequest`/sockets/FTP/mail, no `://`, no
  `requests`/`urllib`/`httpx`/`aiohttp`/`websocket`, no `localhost`/`127.0.0.1`.
- **No broker API outside MT5:** no FIX/cTrader/IB/oanda/binance/ccxt/alpaca.
- **No AI/ML/LLM:** no torch/tensorflow/sklearn/keras/xgboost/transformers/
  openai/anthropic, no `predict(`/`model.fit(`.
- **No strategy execution inside the EA:** no indicator/price-series APIs
  (`iMA`, `iRSI`, `CopyRates`, `CopyBuffer`, …); no external-process execution.
- **No duplicated logic:** exactly one `canonical_json`, one
  `compute_integrity_digest`, one `result_id`, one `validate_record`, one
  `SeenResolver` in the whole system; the adapter reuses them and reimplements
  none.

---

## 9. Remaining risks

1. **O(N²) directory scans (perf).** Large single-directory backlogs degrade
   throughput. Not a correctness issue and outside the strategy's cadence, but a
   scaling risk for high-volume operation. *(Bridge concern — not changed here.)*
2. **MQL5 EA not compiled/run on a live terminal** (carried from Phase 3). The
   Python reference + mock terminal prove the protocol; digest canonicalization
   parity and live-broker behaviour remain to be validated on MetaTrader.
3. **Durability asymmetry.** The Python bridge fsyncs; the MQL5 EA has
   `FileFlush` only (no fsync API), so its power-loss window is slightly larger
   on the real terminal.
4. **Volume sizing gap.** The instruction carries `risk_fraction` but no
   executable volume; the EA uses an operator constant (it must not size from
   risk). A risk-sizing layer upstream of the bridge is required for live sizing.
5. **Reconciliation-required items need an operator.** `RECONCILIATION_REQUIRED`
   is fail-closed by design and awaits external resolution (no auto-retry).
6. **Single-filesystem assumption.** Atomic rename/claim require `bridge_root`
   on one filesystem; the MT5 sandbox/common folder must satisfy this.
7. **Clock/timezone dependence.** Expiry compares against the terminal's
   `TimeGMT()`; a mis-set terminal clock affects expiry decisions.

---

## 10. Production hardening recommendations

1. **Dedup/scan indexing:** make the ledger the O(1) dedup index and avoid
   full-directory scans; bound claim batches; shard/rotate `pending` and
   `results` to keep directories small. *(Future bridge phase.)*
2. **MQL5 go-live gate:** compile in MetaEditor; validate digest parity against
   the reference canonical vectors; soak-test restart in the Strategy Tester and
   on a demo account across all recovery states.
3. **Risk-sizing layer:** stamp an executable `volume` into instructions upstream
   so the EA stays sizing-free.
4. **Reconciliation tooling:** an operator view/alerting for
   `RECONCILIATION_REQUIRED` and `EXECUTION_FAILED`.
5. **Retention/compaction:** archive/results retention policy to bound directory
   sizes and disk.
6. **Observability:** derive metrics from the audit log (counts by reason code)
   and alert on failures/reconciliation.
7. **Throughput:** if higher signal rates are ever needed, batch fsyncs or add a
   write-ahead log.

---

## 11. Blockers

- **MQL5 compile + live-broker validation** cannot run in this environment (no
  MetaTrader terminal / MQL compiler). Carried from Phase 3; not a regression.
  No correctness defects were found in the deterministic substrate.

---

## Final disposition

**READY FOR MULTI-AGENT INTELLIGENCE.**

The deterministic execution substrate — strategy engine → bridge → execution
adapter → recovery → audit — is validated as **reliable**: exactly-once under
duplicates and crashes, fail-closed on every injected failure, byte-deterministic,
boundary-clean, and correct at 1k/5k/10k scale. No correctness defects require
engineering corrections.

This clearance is for building the multi-agent intelligence layer **on top of**
this substrate. It is **not** a live-trading go-live sign-off: before real-money
operation, close the live-trading gates in §9–§11 — compile and soak-test the
MQL5 EA on a real terminal, add the upstream risk-sizing layer, and (only if high
volume is targeted) apply the O(N²) scan hardening.

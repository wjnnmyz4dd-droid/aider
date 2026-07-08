# MT5 EA Bridge — Deployment Guide

How to wire `mt5/PhantomBridgeEA.mq5` and `phantom_pipeline/ea_bridge/`
(`ADR-023`) into a running deployment. **The EA is a transport bridge
only** — it never scores, sizes, or decides a trade. Every decision still
comes from Data Pipeline → Scanner → Strategy Engine → Scoring → Risk →
Compliance → Execution Validator → MT5 Bridge → Position Manager; the EA
only carries an already-approved command onto the MT5 terminal and
reports back what happened.

**Scope note:** this guide covers running the bridge in a demo/paper
environment for validation. It does not authorize live deployment —
see §8.

---

## 1. Architecture recap

```
Phantom (Python)                          MT5 terminal
-----------------                          ------------
MT5Bridge  --(BrokerAdapter ABC)-->  EABrokerAdapter
                                          |
                                     CommandQueue
                                          |
                                   ea_bridge HTTP server  <--HTTP-->  PhantomBridgeEA.mq5
                                   (heartbeat/account/tick/bars/
                                    positions/poll/execution/
                                    error/emergency-stop)
```

`EABrokerAdapter` implements the same `BrokerAdapter` ABC that
`MT5Adapter` (direct `MetaTrader5` package) and `FakeBrokerAdapter` (test
double) already satisfy. `MT5Bridge` itself needs **zero code change** to
use it — you only change which adapter you construct.

## 2. Running the Python side

```python
from datetime import datetime, timezone

from phantom_pipeline.data_pipeline import DataPipeline
from phantom_pipeline.ea_bridge import (
    CommandQueue, EABridgeConfig, EABridgeEngine, EABrokerAdapter, EABridgeMetrics, serve,
)
from phantom_pipeline.mt5_bridge import MT5Bridge
from phantom_pipeline.mt5_bridge.idempotency_store import InMemoryTransportIdempotencyStore

config = EABridgeConfig(
    api_key="<generate a long random secret, never commit it>",
    allowed_symbols=("EURUSD", "GBPUSD", "USDJPY"),
    magic_number=20260708,
)
clock = lambda: datetime.now(timezone.utc)

queue = CommandQueue(config)
adapter = EABrokerAdapter(queue, clock=clock, config=config)
engine = EABridgeEngine(config, DataPipeline(), queue, adapter, metrics=EABridgeMetrics())

# Wire the adapter into MT5Bridge exactly like MT5Adapter/FakeBrokerAdapter --
# no MT5Bridge code change (ADR-023 Hard Rule 2).
mt5_bridge = MT5Bridge(adapter, InMemoryTransportIdempotencyStore(3600.0))

server = serve(engine, config, clock=clock, host="127.0.0.1", port=8787)
server.serve_forever()  # or run on a background thread
```

`mt5_bridge` is not wired into `MT5Bridge` by default anywhere in this
repository (`ADR-023` §7, out of scope) — you make this substitution
explicitly for the deployment that wants an EA-backed terminal instead of
the direct `MetaTrader5` package adapter.

## 3. Installing the EA in MetaTrader 5

1. Copy `mt5/PhantomBridgeEA.mq5` into your terminal's
   `MQL5/Experts/` directory (Terminal → File → Open Data Folder).
2. Open it in MetaEditor and compile (F7). Fix any compiler warnings
   for your MT5 build before proceeding — this repository has no
   MetaEditor available to pre-compile it for you (see §9).
3. In the terminal: **Tools → Options → Expert Advisors** → check
   "Allow WebRequest for listed URL" and add your backend's exact URL
   (e.g. `http://127.0.0.1:8787`). `WebRequest()` silently fails with
   error 4060 if the host isn't allow-listed first.
4. Drag `PhantomBridgeEA` onto a chart for one of your `AllowedSymbolsCsv`
   symbols. Load `mt5/PhantomBridgeEA.set` in the EA properties dialog
   ("Load") to start from the documented defaults, then set `ApiKey` to
   match your `EABridgeConfig.api_key` exactly.
5. Confirm "Algo Trading" is enabled (toolbar button) — MT5 will not let
   the EA place orders otherwise.

## 4. EA input reference

| Input | Purpose |
|---|---|
| `BackendUrl` | Phantom backend base URL (must match the `WebRequest` allowlist) |
| `ApiKey` | Sent as `X-Phantom-Api-Key`; must equal `EABridgeConfig.api_key` |
| `HeartbeatIntervalSeconds` | How often `OnTimer` sends `/ea/heartbeat` |
| `BarSyncIntervalSeconds` | How often `OnTimer` sends `/ea/bars` |
| `AllowedSymbolsCsv` | Comma-separated symbols the EA will tick/bar-sync; empty = current chart symbol only |
| `MagicNumber` | Must equal `EABridgeConfig.magic_number` — orders opened under any other magic number are never touched |
| `MaxSlippagePoints` | Passed to `CTrade` as the execution deviation |
| `FailClosedTimeoutSeconds` | No successful backend contact within this window halts all command polling/execution |
| `EmergencyDisable` | Manual kill switch — the EA never polls or executes while `true`, independent of the backend's own `/ea/emergency-stop` |
| `BarTimeframesCsv` | Timeframes synced via `/ea/bars` (default `M15,H1,H4,D1`) |

## 5. Security checklist

- [ ] `ApiKey` is a long random secret, generated per deployment, never
      committed to source control or shared across environments.
- [ ] `MagicNumber` is unique to this EA instance — every command and
      every reported position is scoped to it (`ADR-023` §3).
- [ ] `AllowedSymbolsCsv` / `EABridgeConfig.allowed_symbols` lists only
      the symbols this deployment actually trades.
- [ ] `BackendUrl` is allow-listed in MT5's Expert Advisor options —
      remove any stale URLs when the backend address changes.
- [ ] The backend key comparison is timing-safe (`hmac.compare_digest`)
      and every command carries a server-issued `execution_id`; the EA
      never invents one, so idempotency and duplicate-execution
      rejection hold end to end (`validation.py`, `CommandQueue`).
- [ ] `command_ttl_seconds` / `FailClosedTimeoutSeconds` are tuned so a
      stale command is dropped, never delivered, if the EA reconnects
      after an outage.

## 6. Fail-closed behavior (both sides)

- **Python side:** `EABrokerAdapter.heartbeat()` returns `False` once
  `heartbeat_timeout_seconds` elapses since the last recorded heartbeat —
  this drives `MT5Bridge.state` to `DISCONNECTED` through the existing
  `ADR-008` §6 mechanism, unchanged. `CommandQueue.enqueue()` also
  refuses new commands outright when the adapter reports it isn't ready.
- **EA side:** `IsFailClosed()` returns `true` once
  `FailClosedTimeoutSeconds` have passed without a successful backend
  contact, or while `EmergencyDisable` is set — in either case the EA
  stops polling and executing commands, though it keeps trying to
  reconnect and report telemetry.
- **Either side alone is sufficient** to stop new execution; both are
  wired so an operator only needs to trust one of them to reason about
  safety.

## 7. Known Phase-1 limitation: JSON handling

MQL5 has no built-in JSON library. `PhantomBridgeEA.mq5` uses a small,
hand-rolled JSON builder/extractor scoped to exactly the fixed message
shapes this bridge sends and receives — it is **not** a general JSON
parser, does not handle nested objects/arrays beyond the one `bars`/
`commands`/`positions` array shape it expects, and will fail loudly
(reported via `/ea/error/report`) rather than guess on anything outside
that shape. If you extend the message schema, extend this parser
deliberately rather than assuming it is general-purpose.

## 8. Do not deploy to live

This guide, `ADR-023`, and the accompanying implementation are scoped to
**demo/paper validation only** (see the ADR's explicit instruction: "Do
not deploy to live. Do not place real trades."). Before any live use:
run the EA against a demo account for an extended period, confirm every
security-checklist item above, and get an explicit, separate go-ahead —
this guide does not grant one.

## 9. Validation status

- All Python-side code (`phantom_pipeline/ea_bridge/`) is compiled,
  unit-tested (see `tests/phantom_pipeline/ea_bridge/`), and verified via
  a full HTTP-stack smoke test covering all 9 endpoints.
- `PhantomBridgeEA.mq5` has **not** been compiled or run — this sandbox
  has no MetaEditor/MT5 terminal. Its correctness rests on careful
  construction against documented MQL5 API semantics (`CTrade`,
  `WebRequest`, `PositionGetTicket`, `CopyRates`, `StringSplit`), not
  automated verification. Compile it in a real MetaEditor and test on a
  demo account before trusting it with even paper capital.

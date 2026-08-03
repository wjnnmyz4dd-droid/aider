# Repository Research — 2 of 5: darwinex/dwx-zeromq-connector

Status: **Complete.** Per the Repository Research Protocol, this covers
exactly one repository. Do not proceed to repo #3 (backtrader) without
explicit approval.

No code was written or copied. This repo was cloned to a scratch
directory for direct source inspection only (not vendored into this
repository, not committed). License: BSD 3-Clause (more permissive than
repo 1's GPLv3) — noted for completeness; moot either way since nothing
is being copied regardless of license.

**Note:** this repo targets **MQL4, not MQL5** — its patterns are
architecturally comparable but the code itself (and its DLL binaries)
are not directly portable to Phantom's MT5 target.

---

## 1. Complete audit

### 1.1 Architecture

**MQL4 side** (single file, no class-per-concern split):
`v2.0.1/mql4/DWX_ZeroMQ_Server_v2.0.1_RC8.mq4` (1332 lines) — one
`Instrument` helper class for rate-publishing dedup, `OnInit`/`OnDeinit`/
`OnTick`/`OnTimer` lifecycle, and `InterpretZmqMessage()`, a big `switch`
on 11 command types (OPEN/MODIFY/CLOSE/CLOSE_PARTIAL/CLOSE_MAGIC/
CLOSE_ALL/GET_OPEN_TRADES/HIST/TRACK_PRICES/TRACK_RATES/GET_ACCOUNT_INFO).

**Python side:** `DWX_ZeroMQ_Connector` class, a background poller thread,
plus an example layer (`DWX_ZMQ_Strategy` base class, execution/reporting
helper modules, a sample multi-symbol strategy).

**3 ZeroMQ sockets** (vs. 7 in repo 1 — same pattern family, fewer
channels): `pushSocket` (PUSH, EA→Python responses), `pullSocket` (PULL,
Python→EA commands), `pubSocket` (PUB, EA→Python broadcast market data).
Strict command/response pair plus a separate broadcast channel — a
cleaner channel count than repo 1, same lack of any security layer.

### 1.2 Communication

Semicolon-delimited positional strings for commands (not JSON), e.g.
`TRADE;OPEN;0;EURUSD;0.0;500;500;DLabs_Python;0.01;123456;0`. Responses
are **Python-dict-literal strings with single quotes** (not JSON), e.g.
`{'_action': 'EXECUTION', '_magic': 123456, '_ticket': 85051741, ...}`,
parsed Python-side with `eval()` — see §1.3. Market data uses a
`SYMBOL:|:payload` topic/payload split for PUB/SUB topic filtering.

**DLL dependency confirmed, not merely suspected.** MQL4 has no native
socket API; the EA depends on `mql-zmq`, itself a thin wrapper around
two compiled native binaries (`libzmq.dll`, `libsodium.dll`) that must be
manually placed in `MQL4/Libraries` and require the MSVC++ 2015 runtime
on the host. The EA even self-checks `IsDllsAllowed()`/
`IsLibrariesAllowed()` before every trading command — an explicit
acknowledgment that "Allow DLL imports" (a real MT4/5 security-relevant
setting letting an EA run arbitrary native code) must be enabled. This
is the same class of exposure flagged in repo 1, now directly confirmed
with named binaries. The DLLs are also MT4-build-specific and would not
carry over to an MT5 port as-is.

### 1.3 Security

**Authentication: none.** All three sockets wildcard-bound (`HOSTNAME="*"`),
plain `tcp://`, no CURVE/PLAIN/ZAP mechanism anywhere. Identical posture
to repo 1 despite the smaller channel count.

**Input validation: minimal.** No arity/schema check before positional
array indexing in `InterpretZmqMessage()` — a malformed short message
would dereference unguaranteed indices. The only enforced numeric bound
is a max-lot-size and max-order-count cap on new orders; no negative/zero
lot check, no symbol-existence check, no SL/TP magnitude bound, no magic
allowlist.

**A new, distinct anti-pattern not present in repo 1: `eval()` used to
deserialize EA responses on the Python side**, over an unauthenticated,
unencrypted TCP channel — a genuine code-injection surface, not just a
parsing shortcut.

**Replay/duplicate protection: none** — no message ID/nonce anywhere in
the 11-field command tuple; the only backstop against a duplicate open is
a blunt max-order-count cap, which limits pile-up but doesn't detect or
reject a duplicate as a duplicate.

**Magic number: a genuine improvement over repo 1, but still incomplete.**
Unlike repo 1's fully decorative field, this repo actually reads the
magic number off the wire and passes it into the real order-placement
call, and its `CLOSE_MAGIC` command correctly filters by magic before
closing. **However**, `CLOSE_ALL` closes every order on the account with
no magic filter at all, and `GET_OPEN_TRADES` lists every order
regardless of magic — so isolation holds for creation and selective
close, but breaks for the two "everything" operations. A materially
better story than repo 1's fully-unenforced field, but still not the
full end-to-end isolation an institutional bridge requires.

### 1.4 Error handling

**A genuine strength, directly answering repo 1's worst defect:** the ack
is built from the real post-execution outcome — `OrderSend`/`OrderModify`
return values and `GetLastError()` are read *after* the broker call, mapped
through a 90-entry error-code table, and only then returned to the
client. The response is never sent before execution is attempted, unlike
repo 1's "OK" sent before validation.

**But the exact same fail-closed gap as repo 1: no timeout on EA-side
client liveness.** The EA's timer/tick loop runs forever regardless of
whether the Python process is alive. A `HEARTBEAT` command exists but is
purely reactive (the EA answers if asked) — nothing tracks time-since-last-
contact or halts trading if the Python side goes silent. This is a
heartbeat primitive that *looks* like a safety mechanism but isn't wired
to any actual safety action — precisely the anti-pattern Phantom's design
must never regress toward.

A real strength: pre-trade capability gating is centralized
(`CheckOpsStatus()`) — one function checks trade-allowed, EA-enabled,
context-free, DLLs/libraries-permitted, and broker-connected before any
of the 11 command types executes, each failure mapped to a distinct
client-visible reason.

### 1.5 Performance

1ms EA timer (command poll cadence), 500ms fallback price refresh,
fully non-blocking I/O on both EA and Python sides (explicit `DONTWAIT`
throughout). No batching for live tick/rate publishing (one message per
changed symbol per loop iteration); historical data responses *are*
batched (one message for the full requested range).

### 1.6 Strengths

- Ack reflects real execution outcome, not intent — the single clearest
  improvement over repo 1's "ack before validation."
- Centralized, command-agnostic pre-trade capability gate.
- Magic number genuinely wired for order creation and selective close.
- Fully non-blocking I/O on both sides.
- Clean shutdown path (explicit unbind/disconnect/context-destroy, thread joins).

### 1.7 Weaknesses

- Zero authentication on all three sockets, identical posture to repo 1.
- No replay/dedup protection.
- No fail-closed timeout on client liveness — same critical gap as repo 1.
- Magic-number isolation incomplete for bulk-close/list-all operations.
- `eval()`-based deserialization over an unauthenticated channel — a new,
  more serious security defect than anything found in repo 1.
- Non-JSON, hand-rolled wire format requiring `eval()` to parse.
- No input arity/schema validation before positional indexing.
- Hard dependency on two compiled native DLLs plus a specific MSVC++
  runtime, Windows-only, explicitly "not tested on WINE/VMWare" per the
  project's own README.
- The maintainer's own README states the project is headed for
  archival — this is not an external judgment, it's stated intent.

### 1.8 Maintenance status

Last commit **2022-05-25** — roughly 4 years stale as of today. **The
maintainer explicitly states in the README that this project will soon
be archived**, superseded by a non-ZeroMQ, DLL-free successor
(`darwinex/dwxconnect`) for both MT4 and MT5 — itself a tacit admission
that the ZeroMQ+DLL transport model audited here was a liability worth
abandoning. License: BSD 3-Clause. 369 stars, 244 forks, 14 open issues —
meaningfully more adoption than repo 1, consistent with a real regulated
broker (Darwinex, UK FCA-regulated) publishing it, but the broker's own
README explicitly disclaims it as "NOT meant to be used as-is." The
corporate origin buys credibility on documentation quality, breadth of
adoption, and execution-error-handling rigor — it does **not** buy
credibility on the transport security model, which shares the same risk
profile as the independent hobbyist repo audited first.

---

## 2. KEEP / IMPROVE / REMOVE / IGNORE

| Item | Verdict | Why |
|---|---|---|
| HTTP + API-key transport (Phantom's existing design choice) | **KEEP** | Reconfirmed again by contrast — even a regulated broker's reference implementation has zero auth on its socket transport |
| Fail-closed timeout on counterpart liveness | **KEEP** | Neither this repo nor repo 1 has one; it remains a hard, non-negotiable Phantom requirement |
| Ack built from real post-execution outcome, never before it | **KEEP** (reinforced) | This repo does it correctly — direct evidence the pattern is achievable even without a framework; Phantom's design must keep matching it |
| Magic number enforced on every mutating/reading operation, not just some | **KEEP** (reinforced) | This repo's partial enforcement (broken for bulk-close/list) is exactly the "don't leave a gap" lesson to keep applying rigorously |
| Safe deserialization (never `eval()` or equivalent) of anything received over the network | **KEEP** (new, explicit) | This repo's `eval()` use is a concrete cautionary example; Phantom's JSON-based HTTP bridge with a real parser already avoids this |
| Centralized, command-agnostic pre-trade capability gate (`CheckOpsStatus` pattern) | **IMPROVE** | Genuinely good idea — one gate enumerating every precondition with a distinct rejection reason per failure, worth adapting into Phantom's Execution Validator/Compliance stage |
| Runtime-reconfigurable market-data subscription (`TRACK_PRICES`/`TRACK_RATES`) | **IMPROVE** (low-medium priority) | Letting the client change which symbols/timeframes stream without restarting the EA is a reasonable future capability for Phantom's bar/tick delivery |
| "On shutdown, actively flatten/clean up" shape (not this repo's unscoped `CLOSE_ALL` implementation) | **IMPROVE** | The *concept* of graceful, active teardown on strategy stop is worth keeping; the *implementation* (unscoped bulk-close) must not be copied — see REMOVE below |
| Separate command/response channel vs. broadcast market-data channel | **IGNORE** | Already achieved in Phantom's design via distinct endpoints; no new information from this repo |
| ZeroMQ + native DLL transport itself | **IGNORE** | Reconfirmed as the wrong choice for Phantom (DLL trust-boundary exposure, MT4/MT5 binary incompatibility, and now also the maintainer's own stated move away from it) |
| Semicolon-delimited / Python-dict-literal wire formats | **IGNORE** | Phantom's JSON schema is already a stricter, safer choice |
| Wildcard bind with zero authentication | **REMOVE** (anti-pattern) | Same verdict as repo 1 |
| `eval()`-based deserialization of network data | **REMOVE** (anti-pattern) | A genuine code-injection surface; never adopt under any framing |
| A "close everything" / "list everything" command that bypasses the isolation scoping every other operation enforces | **REMOVE** (anti-pattern) | Directly violates "no bypass of guards" — any bulk operation Phantom ever adds must be scoped identically to every other operation, with no unscoped variant |
| A heartbeat/liveness primitive that exists but isn't wired to any enforced action | **REMOVE** (anti-pattern) | Worse than no heartbeat at all — it creates false confidence; any heartbeat Phantom implements must be paired with an enforced timeout |
| No input arity/schema validation before positional field access | **REMOVE** (anti-pattern) | Basic defensive-parsing discipline Phantom's structured JSON handling already avoids |

---

## 3. Recommended architecture (provisional — updated from repo 1)

The conclusions from repo 1 hold and are reinforced, not changed, by this
repo. Two refinements to add to the provisional recommendation:

1. **Pre-trade capability gate as a single, explicit, named checklist** —
   rather than scattering "is trading allowed / is the broker connected /
   is the terminal ready" checks across multiple functions, this repo's
   `CheckOpsStatus()` pattern (one function, one ordered list of
   preconditions, one distinct rejection reason per failure) is worth
   adopting as the shape for Phantom's own pre-execution gate.
2. **Every mutating or account-reading operation must carry the same
   isolation scope, with no privileged "everything" variant** — this
   repo's `CLOSE_ALL`/`GET_OPEN_TRADES` gap is a concrete example of what
   to explicitly design against: no bulk operation may exist without the
   same magic-number (or equivalent) scoping every other operation has.

Everything else from repo 1's recommended architecture (§3 of that
report) stands unchanged.

## 4. Original Phantom implementation plan (conceptual — no code, no ADR)

Building on repo 1's plan, two additions:

6. Design the pre-execution gate as one explicit, ordered checklist
   function with a distinct rejection reason per precondition — not
   scattered checks — so it is auditable in one place.
7. Design isolation scoping (magic number or equivalent) as a property
   enforced by the transport/dispatch layer itself for every operation
   type, rather than something each operation's author must remember to
   apply individually — the goal is to make an unscoped "everything"
   operation structurally impossible to add by accident, not just
   discouraged by convention.

## 5. Concepts worth carrying forward (consolidated across repos 1-2)

1. Independent trade-transaction mirroring as a drift-detection cross-check (repo 1).
2. Explicit "gap" sentinel + last-known-good resend on market-data reconnect (repo 1).
3. Named platform-error → stable-string translation (repo 1, reinforced by repo 2's 90-entry table).
4. Centralized, single-checklist pre-trade capability gate (repo 2).
5. Runtime-reconfigurable market-data subscription, without EA restart (repo 2).
6. General pattern of bounded, logged-reason retry on startup connectivity (repo 1).

## 6. Cautionary anti-patterns confirmed across both repos so far

1. Never acknowledge before validating (repo 1's specific defect; repo 2 gets this right — evidence it's achievable).
2. Never let a schema field imply a safety guarantee it doesn't fully enforce (repo 1 fully, repo 2 partially).
3. Never bind trading sockets wildcard with zero authentication (both repos).
4. Never ship without a fail-closed timeout on counterpart liveness (both repos — the single most consistent gap found so far).
5. Never use `eval()`/unsafe deserialization on network data (repo 2, new).
6. Never expose an unscoped bulk operation alongside otherwise-scoped ones (repo 2, new).
7. Never leave a heartbeat/liveness primitive unwired to an actual safety action (repo 2, new — but the same lesson as #4 in a different shape).

---

## Next repository

Per the stated order, repository **3 of 5 — `backtrader`** is next.
**Waiting for your explicit approval before starting that research.**

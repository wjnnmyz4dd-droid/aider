# Session Edge ⟂ Phantom — Separation Audit & Isolation Contract (PR-3R)

Read-only audit of the co-located **Phantom / PhantomEdge** system vs **Session Edge**
(`forex_swing_orb/`). Repo HEAD `fba006c`. **Disposition: B — DOCUMENT / QUARANTINE IN
PLACE.** Phantom is a separate, pre-existing, fully code-isolated system; it is retained
but explicitly labelled and its isolation is now test-enforced. No trading behavior,
strategy, compliance, sizing, or EA code was changed.

## What Phantom is
A modular FX **scanning & scoring** engine (`phantom/`, 27 files) plus a large
institutional analytics/dashboard **Flask server** (`phantom_institutional.py`, ~459 KB).
It produces advisory scores, its own ORB/strategy/risk/"ComplianceEngine", a Prometheus
`/metrics` export, and (in the monolith) optional ML (`sklearn`/`xgboost`) and outbound
data/notification calls (Twelve Data, CFTC, economic calendar, Telegram).

## Provenance
Phantom is the repository's **original** project — first commit `8275be6` (2026-07-01);
`phantom_institutional.py` added `9157c49` (2026-07-02, "recovered verbatim").
Session Edge (`forex_swing_orb/`) was layered in later — `8aa4b3b` (2026-08-03). Root
`README.md`/`AUDIT.md`/`RELEASE.md` are **Phantom's**.

## Reachability — can Phantom interfere with Session Edge?
| Vector | Result |
|---|---|
| `forex_swing_orb` imports phantom (production) | **NO** — zero; guard-tested |
| Session Edge launchers reach phantom | **NO** — `run_session_edge.bat`/`autostart_run.bat` → `forex_swing_orb.runtime.launcher` |
| Broker/order execution in phantom | **NONE** — no `order_send`/MT5 execution anywhere in phantom |
| Phantom sizing reachable as Session Edge live authority | **NO** — separate/inert; PR-3J `compliance/sizing.py` remains the sole reachable lot authority |
| AI/ML influences Session Edge | **NO** — optional ML lives only in `phantom_institutional.py`, never imported by Session Edge |
| Filesystem/protocol collision (bridge/`run_dir`/MemoryStore) | **NONE** — phantom references none of these paths |
| Env-var collision | **NONE** — `PHANTOM_*`/`TWELVE_DATA_API_KEY`/`TELEGRAM_*` vs `SESSION_EDGE_*` (disjoint) |
| Port/process collision | **NONE** — phantom binds `127.0.0.1:8080` (and its own Flask port); Session Edge binds no port |
| Packaging bundles phantom | **N/A** — no `setup.py`/`pyproject.toml`; Session Edge is not pip-packaged |

**Answer: Phantom cannot interfere with, contaminate, or accidentally become part of
Session Edge's live trading path.** Complete code isolation, no execution capability, no
shared protocol/env/port.

## Residual (non-trading) risks — why Disposition B, not A
1. **Documentation identity confusion** — the repo root reads as "Phantom"; a newcomer
   may mistake Phantom for Session Edge.
2. **`run_demo.py` is a trap** — it launches *Phantom's* Flask app, not Session Edge.
3. **Bare `pytest` at repo root** collects Phantom's `tests/` (and
   `phantom_institutional.py` imports), which need uninstalled deps (flask, numpy,
   sklearn, xgboost, websocket-client) → import/collection errors that look like Session
   Edge failures.
4. **`phantom_institutional.py` is a network-active server** (external feeds + Telegram)
   co-located in a trading repo; it must never be started on the trading VPS.

## Isolation contract (enforced)
- No `forex_swing_orb` production module imports `phantom` / `phantom_institutional`.
- Session Edge launchers never reference phantom.
- Phantom references no Session Edge bridge/`run_dir`/MemoryStore path and no
  `SESSION_EDGE_*` env var.
- Session Edge's sole live lot-size authority is
  `forex_swing_orb/compliance/sizing.py::allowable_volume`.
Enforced by `forex_swing_orb/tests/test_phantom_isolation_pr3r.py` (+ existing guards in
`test_signal_engine.py` and `bridge/tests/test_bridge.py`).

## How to run each system
- **Session Edge:** `run_session_edge.bat` or `python -m forex_swing_orb.runtime.launcher`.
- **Session Edge tests:** scope to `pytest forex_swing_orb/` (never bare root `pytest`).
- **Phantom (separate):** `run_demo.py` / `phantom_institutional.py` — with phantom deps
  installed, and **not** on the Session Edge trading VPS.

## Not done here (needs a separate owner-approved task)
Moving Phantom to its own repository (Disposition C) or removing it (Disposition D) is
**out of PR-3R scope**. This PR only documents and test-enforces the separation.

# ⚠️ SEPARATE SYSTEM — NOT part of Session Edge

`phantom/` and the root-level `phantom_institutional.py` are a **distinct, pre-existing
project** ("Phantom" / "PhantomEdge") that happens to share this git repository with
**Session Edge** (`forex_swing_orb/`). They are **not** a component of Session Edge and
must not be treated as one.

Established by the PR-3R provenance/reachability audit (repo HEAD `fba006c`):

- **Provenance.** Phantom is the repository's *original* project (first commit
  `8275be6`, 2026-07-01; `phantom_institutional.py` recovered verbatim in `9157c49`,
  2026-07-02). Session Edge (`forex_swing_orb/`) was added later (`8aa4b3b`,
  2026-08-03). The root `README.md`, `AUDIT.md`, `RELEASE.md` describe **Phantom**, not
  Session Edge; Session Edge's docs live under `docs/` and `forex_swing_orb/`.

- **Isolation (verified).** No `forex_swing_orb` production module imports `phantom` or
  `phantom_institutional` (guarded by tests, incl.
  `forex_swing_orb/tests/test_phantom_isolation_pr3r.py`). Session Edge launchers
  (`run_session_edge.bat`, `autostart_run.bat` → `python -m
  forex_swing_orb.runtime.launcher`) never reference phantom. Disjoint env-var
  namespaces (`PHANTOM_*` / `TWELVE_DATA_API_KEY` / `TELEGRAM_*` vs `SESSION_EDGE_*`),
  no shared filesystem bridge/`run_dir`/MemoryStore paths, no shared port with Session
  Edge (Session Edge binds no port).

- **No trading authority over Session Edge.** Phantom has **no MT5/broker order
  execution path** (its HTTP API is read-only — "scan or an order; it reports state").
  It computes its *own* advisory scores/risk/ORB and, in `phantom_institutional.py`, an
  *optional* ML layer (`sklearn`/`xgboost`) and outbound data/notification calls
  (Twelve Data, CFTC, economic calendar, Telegram). **None of this is reachable from
  Session Edge.** Session Edge's sole live lot-size authority remains
  `forex_swing_orb/compliance/sizing.py::allowable_volume`; its realized-R authority
  remains `forex_swing_orb/manage/outcome.py`.

## Operational rules

1. **Do not deploy phantom on the Session Edge trading VPS/terminal.**
   `phantom_institutional.py` is a network-active Flask server (external feeds +
   Telegram) and must never be started as part of Session Edge operation.
2. **Run Session Edge tests scoped**, e.g. `pytest forex_swing_orb/`, not a bare
   `pytest` at the repo root — the root `tests/` are *Phantom's* and require phantom
   dependencies (flask, numpy, sklearn, xgboost, websocket-client, requests) that
   Session Edge does not install.
3. **`run_demo.py` runs Phantom, not Session Edge.** To run Session Edge use
   `run_session_edge.bat` / `python -m forex_swing_orb.runtime.launcher`.
4. Do not wire any phantom module into a `forex_swing_orb` production path. The
   isolation contract is enforced by test.

This notice is documentation only; it changes no phantom or Session Edge behavior.
Removing or relocating phantom is a separate, owner-approved decision (out of PR-3R
scope).

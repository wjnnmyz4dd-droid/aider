# Vibe-Trading — Phase 0 Repository Baseline & Capability Audit

**Scope:** Establish the Vibe-Trading Forex Swing-ORB project baseline. This
document records the code-traced audit only. **No strategy code, backtest-engine
change, EA generation, or MT5 connection was performed.** The companion
design-only strategy spec is `docs/FOREX_SWING_ORB_SPEC.md`.

All findings below are traced from actual code (file:line) in a fresh clone, not
from README claims. Where the README disagrees with the code, it is called out in
§F.

---

## A. Exact repository and commit audited

| Field | Value |
|---|---|
| Repository URL | `https://github.com/HKUDS/Vibe-Trading` |
| Current branch | `main` |
| HEAD commit | `e0b236caaec12c195305b57dcba8c4bafb18a9b8` |
| HEAD date | 2026-07-31 21:37:35 +0800 |
| Release / version | `0.1.12` (pyproject `version = "0.1.12"`; latest tag `v0.1.12`; HEAD is `v0.1.12-212-ge0b236c`, i.e. 212 commits past the tag) |
| Python requirement | `>=3.11,<3.14` (pyproject; upper bound real — `llvmlite` has no cp314 wheel). Audited with **Python 3.11.15**. |
| OS assumptions | Cross-platform (Linux/macOS/Windows) for core. **Windows-only** optional pieces: the `[mt5]` extra (`MetaTrader5>=5.0.45; sys_platform=='win32'`) and its live MT5 connector/data loader. Docker path is OS-agnostic. |
| License | MIT |

**Installation commands (official):**
- Path A (Docker): `cp agent/.env.example agent/.env` → `docker compose up --build` → `http://localhost:8899`.
- Path B (local, used here): `python -m venv .venv && source .venv/bin/activate && pip install -e .` then `cp agent/.env.example agent/.env` and `vibe-trading`.
- Dev/test extras: `pip install -e ".[dev]"` (CI uses `".[dev,openbb]"`).

**Required / optional model & API credentials:**
- **LLM provider (one required for agent features):** `LANGCHAIN_PROVIDER` + `LANGCHAIN_MODEL_NAME` + a provider key. Default example is OpenRouter (`OPENROUTER_API_KEY`). ~20 providers supported (OpenAI, Anthropic, Gemini, DeepSeek, Groq, Moonshot/Kimi, Qwen/DashScope, Zhipu, MiniMax, NVIDIA, Spark, Z.ai, etc.). Optional native adapters via extras (`[anthropic]`, `[deepseek]`).
- **Data credentials (all optional; free fallbacks exist):** `TUSHARE_TOKEN` (A-share), optional `FINNHUB_API_KEY` / `ALPHAVANTAGE_API_KEY` / `TIINGO_API_KEY` / `FMP_API_KEY` (US-equity fallbacks), `FRED_API_KEY` (macro), Longbridge/Futu creds, `VIBE_TRADING_SEC_UA`. Free no-key sources: yfinance, OKX, Eastmoney/Sina/Stooq/Yahoo, akshare/baostock/mootdx.
- **No credentials are required merely to install, run tests, or run a backtest on synthetic/free data.**

**Supported Forex data sources (code, `backtest/loaders/registry.py:149`):** fallback
chain `["mt5", "akshare", "yfinance", "local"]`. Reality (traced): only **mt5**
(Windows + running terminal, all TFs incl. H4) and **akshare** (daily-only, zero
volume) actually resolve FX pairs; **yfinance is in the chain but cannot resolve
project FX symbols** (dead branch); **yahoo** handles `EURUSD=X` only via the MCP
`get_market_data` tool, not the backtest chain.

**Forex backtest engine location:** `agent/backtest/engines/forex.py`
(`ForexEngine(BaseEngine)`); shared hooks in `agent/backtest/engines/_market_hooks.py`;
core loop in `agent/backtest/engines/base.py` (`run_backtest` @ `base.py:610`);
runner/entry `agent/backtest/runner.py` (forex routing @ `runner.py:1012-1015`).

**Existing MT5/MQL5 export capability:** the `pine-script` skill
(`agent/src/skills/pine-script/SKILL.md`) exports TradingView Pine + TDX + MT5.
The **MT5 output is an indicator-only template stub** (`// === YOUR LOGIC HERE ===`,
`PLOT_ARROW`), explicitly **not an Expert Advisor** and with **no order logic**.
No `.mq5` EA / `OrderSend` generator exists. (A separate `vnpy-export` skill emits
runnable *Python* `CtaTemplate`, not MQL5.)

**Swarm/agent presets relevant to Forex/macro/quant/risk** (`agent/src/swarm/presets/`, 30 total):
- FX/macro: **`macro_rates_fx_desk`** (the only FX-specific preset — rates + FX + commodity + macro PM), `macro_strategy_forum`, `global_allocation_committee`, `geopolitical_war_room`.
- Quant: `quant_strategy_desk`, `factor_research_committee`, `ml_quant_lab`, `statistical_arbitrage_desk`, `pairs_research_lab`, `technical_analysis_panel`.
- Risk: `risk_committee`, `portfolio_review_board`.
- User presets can be added under `~/.vibe-trading/swarm/presets/` with no repo edit.

**Tests & validation commands (from `.github/workflows/test.yml`):**
1. `bash tools/ci_grep_gates.sh` (repo safety gates)
2. `pytest tools/test_ci_env_var_gate.py -q` (env-var gate)
3. Syntax check: `cd agent && python -m compileall -q cli && python -m py_compile api_server.py mcp_server.py src/agent/loop.py src/tools/__init__.py backtest/runner.py`
4. `pytest --ignore=agent/tests/e2e_backtest --ignore=agent/tests/test_e2e_harness_v2.py --cov=agent --tb=short -q`
- Lint tools exist (`ruff`, `black`) but **CI does not gate on them**; no mypy.

---

## B. Installation result

- `python -m venv .venv` + `pip install -e .` → **exit 0**, `vibe-trading 0.1.12`.
- `pip install -e ".[dev]"` → **exit 0**.
- No source changes were made to install. Clean install on Linux/Python 3.11.15.

---

## C. Test results

| Check | Command | Result |
|---|---|---|
| Repo safety gates | `bash tools/ci_grep_gates.sh` | **PASS** (all gates; one benign WARN noted by the gate itself) |
| Env-var gate | `pytest tools/test_ci_env_var_gate.py -q` | **PASS** (23 passed) |
| Syntax/static | `compileall`/`py_compile` (official set) | **PASS** (exit 0) |
| Unit tests (full) | official `pytest` command | **PASS — 6883 passed, 20 skipped, 0 failed** (160.6s) |
| CLI smoke | `vibe-trading --version`, `--help`, `--swarm-presets`, `data --help` | **PASS** |
| Web/API startup | `vibe-trading serve --port 8899` | **PASS** — "Application startup complete"; `/docs`→200, `/openapi.json`→200 (`/`→404, frontend not built — expected) |
| Forex data-load | loader registry `fetch(['EUR/USD'],…)` | **Partial/blocked** — resolves to `akshare`, but its Eastmoney endpoint is unreachable through the sandbox proxy (China host). yfinance branch can't resolve FX symbols; mt5 is Windows-only. Loader wiring is correct; live fetch blocked by network egress, not by a code defect. |
| Forex backtest (minimal) | `ForexEngine.run_backtest` on synthetic EURUSD.FX bars | **PASS** — full pipeline executed, 2 trades, metrics produced (spread/swap/slippage applied). |
| Forex engine + validation unit tests | `pytest tests/test_forex_engine.py tests/test_validation.py` | **PASS** (93 passed) |

Note (secondary finding surfaced by the minimal backtest): running with the
canonical `EUR/USD` symbol **crashed at artifact writing** because the `/` in the
symbol is used verbatim in a CSV filename (`base.py:1239`
`df.to_csv(out/f"ohlcv_{code}.csv")` → `ohlcv_EUR/USD.csv` → missing dir). Using
`EURUSD.FX` succeeds. See §F.

---

## D. Forex capability matrix (code-traced)

| Capability | Native? | Evidence / notes |
|---|---|---|
| Forex OHLC loaded natively | **Partial** | Chain `mt5→akshara→yfinance→local`. Real FX resolution only via **mt5** (Windows+terminal) or **akshare** (daily-only, `volume=0`). yfinance can't map FX symbols; no oanda/alphavantage/ccxt FX. `registry.py:149`, `akshare_loader.py:153,217-243`, `yfinance_loader.py:51-74,227`. |
| Supported FX symbols / format | Yes (constrained) | Backtest classifier accepts **`EUR/USD`** or **`EURUSD.FX`** only (`_market_hooks.py:46-47`); bare `EURUSD` / `EURUSD=X` misroute to `a_share` default (`_market_hooks.py:83`). Engine normalizes internally to `EUR/USD` (`forex.py`). |
| Intraday & higher TFs | Yes (bounded) | Backtest `_VALID_INTERVALS = {1m,5m,15m,30m,1H,4H,1D}` (`runner.py:51`). **W1/MN rejected** by runner. **H4 FX only via mt5**; akshare is **daily-only**. |
| Bid/ask **spread** modeled | **Yes** | Static per-pair pip table `_SPREAD_PIPS` (EUR/USD=1.0, default 2.0), half-spread on each fill (`forex.py:25-37,116-122`). Not from real quote data. |
| **Commission** modeled | **No (deliberate)** | `ForexEngine.calc_commission → return 0.0` (`forex.py:88-96`); cost captured via spread. |
| **Swap / rollover** modeled | **Yes** | `calc_forex_swap` applied per bar incl. **Wednesday triple** (`forex.py:124-132`, `_market_hooks.py:242-303`). Tables cover ~7 majors; default `-1.0`/lot otherwise. |
| **Slippage** modeled | **Yes** | `slippage_pips` default 0.3, added to half-spread (`forex.py:73,121`). |
| Sessions / timezones / DST | **No** | No London/NY/Tokyo/Sydney session logic, no weekend-gap, no DST anywhere in `backtest`/`src`. All tz handling is "strip to tz-naive". `ForexEngine.can_execute → True` unconditionally (`forex.py:76-78`). "24x5" is a docstring claim only. |
| **Walk-forward** validation | **Partial / mislabeled** | `walk_forward_analysis` (`validation.py:203-280`) splits the finished equity curve into N windows for a **consistency** check — **no IS/OOS split, no re-optimization**. Not true WFO. |
| **Monte Carlo** validation | **Yes (specific kind)** | `monte_carlo_test` (`validation.py:29-112`) = **trade-order permutation** test (p-values on Sharpe/DD), **not** synthetic price paths. |
| **Bootstrap** validation | **Yes (IID)** | `bootstrap_sharpe_ci` (`validation.py:131-190`) = IID resampling of daily returns (**no block bootstrap**; ignores autocorrelation). |
| Validation asset-agnostic for FX | **Yes** | Generic inputs; wired in `base.py:778-780`; runs for FX. Caveat: `bars_per_year` defaults 252 — must be set correctly for intraday FX annualization. |
| MT5 export = executable MQL5? | **No** | Indicator-only template stub, "not an Expert Advisor", no `OrderSend`, LLM-filled (`pine-script/SKILL.md:271,317-319,344,371`). |
| Broker / live-execution code exists? | **Yes (substantial)** | Real order placement for ~10 connectors incl. **MT5 `order_send`** (`mt5/orders.py:150`). Fail-closed live gate (`live/sdk_order_gate.py:59`), mandate/HardCaps (`live/enforcement.py`, `live/mandate/`), **filesystem kill-switch/halt** (`live/halt.py`), daily counters, audit log. IBKR read-only; Robinhood MCP-gated. |

---

## E. Exact extension points identified

**Cleanest extension point for a custom Swing-ORB strategy — the `SignalEngine`
file contract (no core edit):**
- Contract: `agent/src/skills/strategy-generate/SKILL.md:47-70` — a class
  `SignalEngine` with `generate(self, data_map: Dict[str,pd.DataFrame]) ->
  Dict[str,pd.Series]` returning a per-bar signal in `[-1.0, 1.0]`.
- Loaded from `<run_dir>/code/signal_engine.py` (`runner.py:915`, `:174-175`),
  executed by `BaseEngine` (`base.py:614-651`), forex engine auto-selected for
  `EUR/USD` (`runner.py:1012-1015`). Invoked via the `backtest(run_dir=...)`
  agent/MCP tool (there is **no** `backtest` CLI subcommand).
- An **AST security scrubber** restricts what the file may execute
  (`runner.py:432-519`); `__init__` must take no required args.
- **Caveat:** the signal is a directional weight per bar, **not** a bracket
  order. ORB stop/target must be encoded as position changes inside `generate()`
  — the engine models no broker-side SL/TP.
- The factor "Alpha Zoo" (`src/factors/`) is a code registry via
  `__alpha_meta__` dicts, but its `Universe` literals are **equity/crypto/futures
  only (no forex)** (`factors/registry.py:66`) — wrong abstraction for FX ORB.

**Cleanest future extension point for an MT5 execution bridge — the existing live
mandate gate (adapter already exists; do not build new):**
- `agent/src/live/sdk_order_gate.py:59` `execute_live_order(...)` is the canonical
  "consume instruction → fail-closed checks → `connector.place_order`" seam,
  already fronting every direct-SDK broker (mandate load, expiry, halt/kill,
  notional normalization, mandate check, daily count, audit).
- MT5 connector already registered: `service.py:26` (`"mt5":
  "src.trading.connectors.mt5.sdk"`); order path `mt5/orders.py:59` →
  `mt5.order_send` (`:150`); size guards `mt5/orders.py:257`; profiles
  (readonly/paper/live) `mt5/profiles.py:6-70`.
- **Bridge plan:** define a trade-instruction dataclass (see gap below) →
  translate to `OrderIntent` (`live/enforcement.py:111-134`) + `place_kwargs` →
  `execute_live_order(broker="mt5", connector_module=<mt5.sdk>, ...)`. Reuses
  guards/halt/audit with zero core change. Live-loop layer: `agent/src/live/runtime/`.
- **Gap:** no existing model carries `entry/stop/target/expiration/evidence/
  version`; `OrderIntent` carries only `symbol/side/notional/quantity/
  instrument_type/asset_class`; MT5 `place_order` exposes no SL/TP/expiration.
  The instruction schema (spec §7) is new work for a later phase.

---

## F. README claims that do NOT match the code

1. **"Walk-Forward validation"** (README lines ~195, 323, 559): implies true
   walk-forward optimization. Code is a **consistency-across-windows** check with
   **no in-sample/out-of-sample separation and no re-optimization**
   (`validation.py:203-280`).
2. **"Monte Carlo"** (same lines): implies price-path simulation. Code is a
   **trade-order permutation** test (`validation.py:73`).
3. **"Bootstrap"**: is **IID**, not block bootstrap — serial correlation not
   preserved (`validation.py:172`).
4. **`/pine` "exports strategies to … MetaTrader 5 (MQL5)"** (README line ~192,
   268, 324): the MT5 output is an **indicator-only template stub, explicitly
   "not an Expert Advisor," with no order/position logic**, and is LLM-filled
   (`pine-script/SKILL.md:271,317-319,344`). It is not an executable strategy/EA.
5. **Forex data breadth** (README line ~358 lists `mt5 · yfinance · akshare ·
   local`): in code, **yfinance cannot resolve project FX symbols** and is a dead
   branch in the forex chain; usable FX is effectively **mt5 (Windows) or akshare
   (daily-only)**.
6. **Intraday FX bars "1m/5m/15m/30m/1H/4H/1D"** (README line ~559): true only
   via **mt5** (Windows). Off-MT5, the only working FX source (akshare) is
   **daily-only** and rejects intraday.
7. **Secondary code defect (not a README claim):** the backtest's own FX symbol
   format `EUR/USD` breaks artifact CSV writing due to the `/` in the filename
   (`base.py:1239`); `EURUSD.FX` works. A symbol/filename-sanitization tension.

---

## G. Contents of docs/FOREX_SWING_ORB_SPEC.md

Created as a **design-only** first-candidate specification (no implementation).
See the companion file `docs/FOREX_SWING_ORB_SPEC.md`. It fully specifies:
market/style, timeframes, London-anchored opening range with explicit DST
handling, deterministic H4+D1 bias (fail-closed on neutral/conflict), closed-bar
breakout with volatility buffer and no breakout-candle entry, retest with
tolerance and range-reclaim invalidation, deterministic continuation
confirmation, symmetrical entry with a full signal/instruction field list,
0.25% risk with correlated-exposure and daily/total fail-closed loss controls,
structural stop with max-stop protection, fixed-multiple (RR=2.0) profit target
(with (b)/(c) alternatives deferred), session/news/spread/stale-data filters,
fail-closed failure semantics, and the validation plan (with the platform
caveats from §D/§F). All parameters are provisional/unoptimized.

---

## H. Proposed integration map

| Vibe-Trading component (exists today) | Swing-ORB responsibility (research/qualification) | Future Titan EA responsibility (execution) | Phantom component that may be *selectively evaluated* later |
|---|---|---|---|
| Data loaders (`backtest/loaders/`, `mt5_loader`, akshare) | Source EURUSD OHLC (D1/H4/M15); enforce completeness/stale-data checks | (reads its own broker feed at run time) | — |
| Backtest engines (`ForexEngine`/`BaseEngine`) | Run/validate the Swing-ORB `SignalEngine`; costs (spread/swap/slippage) | — | — |
| `SignalEngine` contract (`skills/strategy-generate`) | **Primary home of Swing-ORB logic** (opening range, bias, breakout, retest, confirmation) | — | Phantom `orb.py` / `strategies/orb_strategy.py` as a *reference* for ORB structuring only (no merge) |
| Validation (`backtest/validation.py`) | MC (permutation) + IID bootstrap + window-consistency; **external true WFO + IS/OOS orchestration added around it** | — | — |
| Signal/instruction schema (**new, to define**) | Emit versioned, expiring trade instruction (symbol/dir/entry/stop/target/ts/evidence/expiration) then **write it to the filesystem outbox** | **Claim** the instruction file, validate, execute; **write a result** to the inbox | Phantom score/decision (`scorer.py`,`scanner.py` `APPROVE/WATCHLIST/BLOCK`) as an optional *qualification gate* input — evaluation only |
| **Local filesystem execution bridge** (**new; design-only, `docs/FILESYSTEM_EXECUTION_BRIDGE_SPEC.md`**) | **Producer:** atomic-write instructions to `outbox/pending/`; ingest `inbox/results/` for analytics/audit. **No MT5/network.** | **Consumer:** atomic-claim `pending→claimed`, run the ordered validation gate, execute, write exactly one result; dedup + reconcile | — (Phantom not involved in the transport) |
| Live gate (`live/sdk_order_gate.py`), mandate (`live/mandate/`), halt (`live/halt.py`) | — | **Reuse** as the fail-closed execution boundary **behind the bridge consumer** | Phantom `guards.py`/`risk.py` (spread/news/correlation/exposure/RR) as candidate parity checks — evaluation only |
| MT5 connector (`trading/connectors/mt5/`) | — | **Reuse** `place_order`/size-guards; add ticket-pinned flatten + SL/TP surface | — |
| Swarm presets (`macro_rates_fx_desk`, `risk_committee`, `quant_strategy_desk`) | Optional research/qualification context around the strategy | — | — |

**Titan (future EA) provisional posture** — Titan is the preferred starting point
for the lightweight MT5 execution EA; it will **not** own strategy research or
qualification. It receives a **fully formed, versioned, expiring** trade
instruction and independently enforces account/symbol/duplicate-position/
lot-size/stop-distance/spread/stale-signal/kill-switch protections. These map
directly onto the existing `sdk_order_gate` + mandate + `halt` primitives, which
the EA either reuses (Python-side) or re-implements broker-side in MQL5.

**Coupling = local filesystem only (no networking).** The SignalEngine and Titan
are decoupled by a **local filesystem execution bridge** (full contract in
`docs/FILESYSTEM_EXECUTION_BRIDGE_SPEC.md`): the producer atomically writes a
versioned instruction to `outbox/pending/`; Titan atomically claims it to
`outbox/claimed/`, runs an ordered fail-closed validation gate, executes, and
writes exactly one terminal result to `inbox/results/`, which Vibe-Trading ingests
for audit/reconciliation. The bridge uses **only** filesystem operations
(temp-write + `fsync` + atomic rename, content-hashed `signal_id` filenames,
persistent restart-surviving dedup) — **no HTTP/localhost/sockets/ports/WinINet/
WebRequest**. It is **design-only** and its implementation begins **only after
Swing-ORB Phase 1 acceptance** (Phase 1 does not write to the bridge).

---

## I. Provisional decision recorded (execution layer, future)

- **Titan is the preferred starting point** for the lightweight MT5 execution EA.
- Titan will **not** own strategy research or qualification.
- The EA will receive a **fully formed, versioned, expiring** trade instruction.
- The EA will **independently enforce** account, symbol, duplicate-position,
  lot-size, stop-distance, spread, stale-signal, and kill-switch protections.
- **Phantom** risk/position-management logic may be **selectively evaluated
  later**; **no full Phantom merge is authorized.**
- Titan repository must **not** be modified in this phase; Phantom must **not** be
  modified; no code from Phantom or Titan is merged yet.

---

## J. Risks and blockers

1. **Intraday FX off-Windows is effectively unavailable.** H4/M15 FX bars require
   MT5 (Windows + running terminal). akshare is daily-only with zero volume, and
   the sandbox proxy blocks its (China) endpoint. **Blocker for intraday
   backtests until a real intraday FX source is wired** (e.g. an OANDA/Dukascopy
   loader, or MT5 on Windows, or a local CSV via `local_loader`).
2. **Validation semantics ≠ labels.** "Walk-forward" is not true WFO; "Monte
   Carlo" is a permutation test; bootstrap is IID. True IS/OOS walk-forward and
   price-path MC must be orchestrated externally (spec §13). Risk of
   over-trusting the built-ins.
3. **No session/timezone/DST modeling** in the engine, yet the strategy is
   London-session-anchored. The strategy layer must supply all session/DST logic;
   the backtest cannot express weekend gaps or session hours natively.
4. **Symbol-format fragility / artifact bug.** `EUR/USD` is required by the FX
   classifier but breaks artifact CSV writing (`/` in filename); `EURUSD.FX` is
   the safe canonical for run configs. Bare `EURUSD`/`EURUSD=X` misroute to
   `a_share`. Must be handled deterministically (spec §12).
5. **No executable MQL5 EA generator.** Any EA is new work (Titan). The existing
   MT5 "export" is a chart-indicator stub, not executable strategy code.
6. **No unified trade-instruction schema** carrying entry/stop/target/
   expiration/evidence/version. Must be defined before an execution bridge.
7. **Commission is hard-zero** in the FX engine (spread-only cost model) —
   acceptable but must be stated in every result.
8. **Network egress in this environment** is restricted (China data hosts and
   some tickers blocked), so live FX data-load and full e2e data tests could not
   be exercised end-to-end here; loader *wiring* was verified, live *fetch* was
   not.

---

*Phase 0 stops here. No implementation begun. Deliverables:
`docs/FOREX_SWING_ORB_SPEC.md` (design-only spec) and this audit.*

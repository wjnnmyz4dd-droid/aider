# VIBE Trading (HKUDS/Vibe-Trading) — Research Lab Evaluation

Status: Research report only. No Phantom code modified. VIBE not cloned,
installed, or connected to anything. No code written.

Owner: Software Architect (per `.claude/agents/TEAM.md` RACI — cross-repo
architecture questions are its lane)

Date: 2026-07-04

Source: browsed via GitHub/raw-content fetch (17.7k★, 2.9k forks, MIT
license, Python 3.11+, last activity today).

---

## 1. Architecture summary

VIBE is an LLM-agent research platform, not a backtesting library with an
agent bolted on — the agent loop is the product; backtesting is one of ~79
"skills" it can invoke. Shape:

```
Natural-language prompt
  → LangChain/LangGraph agent loop (13+ LLM providers)
  → tool/skill registry (79 finance skills, 54 MCP tools)
  → agent/backtest/ (engines, loaders, optimizers, validation)
  → report (HTML/PDF via jinja2+weasyprint, matplotlib charts)
  → optional: broker connectors (read-only / paper / bounded-live / full-remote)
```

FastAPI backend + React 19 frontend + CLI + MCP server are four different
front doors onto the same agent core. Persistent state lives in
`~/.vibe-trading/` (memory, skills, connector config, cache) — this alone
means VIBE must run in its own environment with its own filesystem
namespace; it is not designed to be imported as a library.

This is architecturally the opposite shape from Phantom's ADR-001 pipeline
(fixed, single-responsibility stages, no LLM in the decision path). That's
correct and expected — VIBE is a *research assistant*, Phantom is a
*deterministic execution pipeline*. The evaluation below treats that as a
feature, not a mismatch: VIBE's job is to help a human form and validate a
hypothesis; Phantom's job is to execute an approved, fully-specified
strategy deterministically. They should never be architecturally similar.

---

## 2. Evaluation against the 15 criteria

| # | Criterion | Finding |
|---|---|---|
| 1 | **Backtesting** | `agent/backtest/` — `engines/`, `runner.py`, `benchmark.py`, `correlation.py`, `models.py`, `run_card.py`. Multi-asset (equity, futures, options, crypto, forex). Real, non-trivial implementation. |
| 2 | **Walk-forward testing** | `validation.py::walk_forward_analysis()` — confirmed real: partitions the equity curve into sequential non-overlapping windows, computes per-window return/Sharpe/drawdown/win-rate. |
| 3 | **Monte Carlo testing** | `validation.py::monte_carlo_test()` — confirmed real: permutation test that shuffles trade PnL order and computes p-values for Sharpe/drawdown against the random distribution. This is the statistically correct way to ask "is this edge real or ordering luck," and directly closes the gap flagged in `TEAM.md` §6 (no agent currently validates strategy-edge significance). |
| 4 | **Strategy optimization** | **Not what it sounds like.** `agent/backtest/optimizers/` (`mean_variance.py`, `risk_parity.py`, `equal_volatility.py`, `max_diversification.py`) is **portfolio-allocation** optimization — how to weight multiple already-chosen assets/strategies — not hyperparameter/parameter search over a single strategy's tunables (no grid search, genetic, or Bayesian optimizer found). If you want ORB-parameter or `StrategyParams` tuning, VIBE doesn't provide it. |
| 5 | **Market data ingestion** | 18 sources with automatic fallback chains (tencent, mootdx, eastmoney, baostock, akshare, tushare, yahoo/yfinance, okx, ccxt 100+ crypto exchanges, finnhub, tiingo, FMP...). Heavily weighted toward China A-share/HK/US equities and crypto; forex/CFD coverage is present but not the center of gravity. |
| 6 | **Trade-history analysis** | "Shadow Account" extraction — compares actual broker trade journals against rule-based backtests, plus behavioral diagnostics. Genuinely useful concept: a way to check whether live Phantom trades matched what the strategy *should* have done. |
| 7 | **Report generation** | `jinja2` + `weasyprint` (HTML→PDF) + `matplotlib` confirmed in dependencies — real report-generation stack, not just console output. |
| 8 | **Natural-language research tasks** | This is the core product: persistent cross-session memory, multi-agent "swarm" teams (investment committee, quant desk, risk team), a "Research Goal runtime" with persistent hypothesis tracking. Directly matches the "Research idea →" entry point of the desired flow. |
| 9 | **Broker integrations** | Read-only: IB (TWS/Gateway), Longbridge, Futu. Paper + bounded live: Tiger, Alpaca, OKX, Binance, Dhan, Shoonya. Full remote: Robinhood Agentic Trading. **No MT5 broker connector exists.** The only MT5 reference found anywhere is the README's claim of exporting a validated strategy to "MetaTrader 5 format" — i.e. codegen of a strategy definition, not a live connector. Could not independently verify that export code (GitHub code search requires login from this environment); treat its exact behavior as unverified either way — it doesn't change the verdict below. |
| 10 | **Risk/portfolio analytics** | `metrics.py`: total/annual return, Sharpe, Sortino, Calmar, Information Ratio, max drawdown, win rate, profit factor, max consecutive losses, avg holding period, per-symbol and per-exit-reason breakdowns. Meaningfully richer than Phantom's current `analytics.py` (`trades/win_rate/profit_factor/pl` only). **Gap:** no VaR, CVaR, or exposure-at-risk metrics found. |
| 11 | **Dependencies** | Core numerical stack is reasonable and Phantom-compatible in spirit: `numpy`, `scipy`, `pandas<3.0`, `scikit-learn`, `duckdb`, `bottleneck`. `smartmoneyconcepts` (PyPI) is notable — an established, independent implementation of BOS/CHOCH/liquidity-sweep/FVG/order-block detection, i.e. the same concepts Phantom hand-rolls in `structure.py`. Everything else — `langchain`/`langgraph` (pinned, heavy), `fastmcp`, and ~15 optional IM-channel extras (Slack/Discord/Telegram/WeChat/Matrix/WhatsApp/QQ/DingTalk/Feishu/MS Teams) — is pure agent-platform weight Phantom has no use for. |
| 12 | **MIT/license compatibility** | MIT, confirmed. Fully compatible with borrowing/adapting code into Phantom (or a separate research repo) with attribution retained; no copyleft obligation. |
| 13 | **Security risks** | `SECURITY.md` confirms VIBE executes **LLM-generated Python strategy code locally** in "a narrow subprocess environment" that excludes API keys/trading secrets but remains **network-capable**. That is a real attack surface (prompt injection → generated code → network call) if VIBE ever shares a network path or credential store with anything broker- or MT5-adjacent. Also flags wallet-connection phishing scams targeting its Discord community — irrelevant to us since no crypto wallet would ever be connected, but confirms this is an actively-targeted, widely-used project (attacker attention is a maintainability/trust signal, not necessarily a flaw). |
| 14 | **Maintainability** | 17.7k★/2.9k forks, MIT, `CONTRIBUTING.md`/`CODE_OF_CONDUCT.md`/`CHANGELOG.md`/`AGENT_CONTRIBUTOR_GUIDE.md` present, dev extras include `pytest`, `pytest-cov`, `pytest-socket` (network-call-blocking in tests — a good sign for a project this network-heavy). Healthy OSS hygiene. |
| 15 | **Helps Phantom or adds noise** | Split verdict, not a single answer — see §6. |

---

## 3. Useful modules

- `agent/backtest/validation.py` — walk-forward, Monte Carlo permutation, bootstrap Sharpe CI. Directly fills Phantom's identified strategy-edge-validation gap.
- `agent/backtest/metrics.py` — richer performance-metric set than Phantom's current analytics.
- Shadow Account concept (live-vs-backtest trade comparison) — a genuinely useful pattern for post-deployment forward-test verification.
- `smartmoneyconcepts` (its dependency, not its code) — an independent reference implementation of the same structure signals Phantom hand-rolls, useful as a correctness cross-check.
- Report-generation stack (jinja2/weasyprint/matplotlib) as a pattern, not a dependency to take on directly.

## 4. Useless modules (for Phantom's purpose)

- The entire agent/LLM loop, 79-skill registry, 54 MCP tools, multi-agent swarm, persistent memory system — this is the product's core, and it's precisely the part Phantom's ADR-001 pipeline must never contain (Phantom has no LLM in its decision path by design).
- All 16 IM-channel adapters (Slack/Discord/Telegram/WeChat/Matrix/WhatsApp/QQ/DingTalk/Feishu/MS Teams/email).
- All broker connectors, at every tier (read-only through full-remote) — none are MT5, all are out of scope by your explicit rule regardless.
- FastAPI/React/Docker delivery layer — VIBE's product packaging, not research logic.
- Portfolio allocation optimizers (`optimizers/`) — not wrong, just answering a different question (multi-asset weighting) than what "strategy optimization" likely means for a single-symbol FX playbook.

## 5. Integration risks

- **Prompt injection → code execution.** VIBE runs LLM-generated code locally. Even sandboxed and credential-excluded, it is network-capable. If a research VM ever shares a network segment, credential store, or filesystem with anything MT5-adjacent, this becomes a real path from "research idea" to "unintended network action." Mitigation is environmental, not architectural: fully separate machine/container/venv, no shared secrets, no outbound path to the broker or MT5 terminal.
- **Dependency bloat as an attack surface.** ~30+ optional extras, 18 data-source SDKs, multiple broker SDKs — a large third-party dependency surface if installed in full. Install only the extras actually needed for backtesting/validation/reporting; skip every IM-channel and broker extra.
- **"MT5 export" feature is a standing temptation.** Even though it's (per README) offline codegen rather than a live bridge, it's the one feature in this repo that could look like a shortcut straight into Phantom. It must not be used that way — see Recommended path below.
- **License hygiene.** MIT permits borrowing, but if any code (not just concepts) is copied, retain VIBE's attribution/NOTICE per MIT terms in whatever research repo houses it.

## 6. Classification

| Component | Classification | Why |
|---|---|---|
| `agent/backtest/validation.py` (walk-forward, Monte Carlo, bootstrap) | **ADAPT** | Closest existing thing to Phantom's missing strategy-edge validation checklist. Port the *methodology*, not necessarily the literal file, into the research lab; add the lookahead-bias/purity gate this file itself is missing. |
| `agent/backtest/metrics.py` | **ADAPT** | Use as a reference for which metrics a Phantom-adjacent research lab's Analytics should compute; don't import wholesale given the unrelated dependency chain it sits in. |
| Shadow Account (live-vs-backtest comparison) concept | **ADAPT** | Valuable pattern for verifying Phantom's live forward-test trades against what the strategy should have done — reimplement narrowly against Phantom's own trade journal format. |
| `agent/backtest/engines/`, `loaders/` (multi-asset backtest engines, 18 data sources) | **KEEP SEPARATE** | Legitimate, working research infrastructure — run it as-is inside VIBE, in its own environment, rather than reimplementing. Don't pull it into Phantom. |
| Agent loop / LLM orchestration / 79 skills / MCP tools / swarm | **KEEP SEPARATE** | This is the whole point of a research lab: let VIBE be VIBE, entirely outside Phantom's process and repo. |
| Report generation (jinja2/weasyprint/matplotlib pipeline) | **KEEP SEPARATE** (pattern may inform Phantom's own reporting later, but not now) | Not on Phantom's critical path; ADR-010 (Analytics) can decide independently whether Phantom needs generated reports. |
| Portfolio allocation optimizers (`mean_variance`, `risk_parity`, etc.) | **IGNORE** (for now) | Solves a multi-asset allocation problem Phantom doesn't currently have (single-symbol FX/CFD playbooks). Revisit only if Phantom grows a multi-symbol portfolio-sizing need. |
| All broker connectors (every tier) | **IGNORE** | Out of scope by explicit rule; none are MT5 regardless. |
| All 16 IM-channel adapters | **IGNORE** | No relevance to a research-only lab. |
| "Export to MetaTrader 5 format" codegen feature | **IGNORE — do not use as an integration shortcut** | This is exactly the boundary your rules draw. A strategy graduates from VIBE to Phantom via human review and reimplementation in Phantom's own Strategy Engine (ADR-003), never via consuming VIBE-generated code, MT5-formatted or otherwise. |
| `smartmoneyconcepts` dependency (SMC/ICT indicator library) | **ADAPT / cross-check only** | Not part of VIBE's own code — a third-party library VIBE happens to depend on. Worth running against Phantom's `structure.py` outputs as an independent correctness check on BOS/CHOCH/FVG/order-block detection, entirely outside both codebases' execution paths. |

## 7. Best parts to borrow

1. The **statistical validation trio** (walk-forward / Monte Carlo permutation / bootstrap CI) — this is the single highest-value thing in the repo relative to Phantom's actual gap.
2. The **Shadow Account** pattern — comparing live results against a rule-based backtest is exactly what a post-deployment forward-test check should do.
3. The **richer metrics vocabulary** (Sortino, Calmar, Information Ratio) as a checklist for what "good" analytics should report, even if reimplemented narrowly.

## 8. What NOT to borrow

1. Any of the agent/LLM/tool-calling machinery — Phantom's decision pipeline must stay deterministic and LLM-free per ADR-001.
2. Any broker or MT5-adjacent code — no exceptions, per your explicit rule.
3. The dependency footprint wholesale (`langchain`/`langgraph`/`fastmcp`/IM extras) — importing the package as-is would drag all of this into a "research lab" that's supposed to be lightweight and isolated.
4. The portfolio-allocation optimizers — a different problem than the one Phantom currently has; adopting them now would be solving a problem you don't yet have, which cuts against the Minimal Change / no-over-engineering rule already governing this project.

## 9. Recommended clean integration path

Matches the flow you specified, made concrete:

1. **VIBE runs standalone**, in its own machine/container/venv, with its own repo (or a fork), never installed into or imported by the Phantom repository. No shared filesystem, credentials, or network path to MT5.
2. **Research idea → VIBE backtest / Monte Carlo / walk-forward → report.** Use VIBE's existing engines and validation module as-is (`KEEP SEPARATE`) to iterate on a hypothesis.
3. **Report → human approval.** A person reads VIBE's output (win rate, Sharpe, Monte-Carlo p-value, walk-forward consistency) and decides whether the edge is real and worth building.
4. **Phantom implementation.** Only on approval, a human (or Minimal Change Engineer, per `.claude/agents/TEAM.md`) reimplements the *validated logic* — not VIBE's code — as a new playbook inside Phantom's own Strategy Engine (ADR-003), through the Engineering Council's normal review pipeline. This is a rewrite by construction, not a port, which is exactly what keeps the research and execution layers separate.
5. **Forward test → live deployment** proceeds entirely inside Phantom's own pipeline (ADR-001 through ADR-010), with no further VIBE involvement.

The one thing this path deliberately forecloses: there is no automated or semi-automated pipe from VIBE's output directly into Phantom, ever. The human-approval step is a hard gate, not a formality.

## 10. Final verdict

**Worth keeping as a separate research lab. Not worth integrating, importing, or connecting.**

VIBE's core research/validation logic — specifically the walk-forward,
Monte Carlo, and metrics modules — is genuinely useful and fills a real,
previously-identified gap in Phantom's own governance (`TEAM.md` §6). But
that value is entirely in the *methodology*, not the codebase: 80%+ of
this repository (agent loop, 79 skills, MCP server, 16 chat integrations,
7 tiers of broker connectors) is infrastructure for a completely different
product — a conversational trading assistant — and would be pure noise
and pure risk (prompt-injection-adjacent code execution, huge dependency
surface, a standing "export to MT5" temptation) if pulled anywhere near
Phantom's execution path.

Recommendation: stand VIBE up in total isolation as the research lab it's
being evaluated to be, adopt its validation methodology as the template
for whatever Phantom's own research-gate checklist becomes, and enforce
the human-approval boundary in §9 as a hard architectural rule, not a
convention.

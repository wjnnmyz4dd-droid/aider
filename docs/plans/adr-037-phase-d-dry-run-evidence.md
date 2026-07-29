# ADR-037 Production Activation — Phases A–D Evidence Record

**Governing Plan:** `docs/plans/adr-037-production-activation-plan.md`
(revised, commit `bb8b4a6`, independently re-reviewed and reconfirmed
CONFORMS in this same pass).

**Authorization scope of this document:** Phases A–D only (§11 of the
Plan). **This document does not authorize, and does not claim to
authorize, Phase E or Phase F.** Gate A broadening, `cross_pair_selection_
enabled=True`, and live Bridge submission for ORB remain prohibited in
any running production deployment until a separate, explicit Phase E
activation review and authorization occurs.

---

## 1. Implementation commit

This evidence record is committed in the same commit as the Phases A–D
implementation it describes. See the commit this file ships in (`git log
-1 -- docs/plans/adr-037-phase-d-dry-run-evidence.md` from this point
forward) for the exact hash; the parent commit is `bb8b4a6` (the
independently-reviewed, revised Production Activation Plan).

## 2. Files changed (Phase A + Phase B + Phase D support)

**Phase A — activation-support code / config loading (§3, §5):**
- `deployment_windows/config_loader.py` — new `opportunity_selection_engine`
  JSON section parser, mirroring the existing `opening_range_anchors`
  pattern; fails closed on malformed `session`/`anchor_hour_utc`/
  `anchor_minute_utc`/`cross_pair_selection_enabled`/`tie_tolerance`
  values; a missing section, or a missing key within it, preserves the
  identical `OpportunitySelectionEngineConfig()` dataclass defaults
  (`enabled_windows=()`, `cross_pair_selection_enabled=False`,
  `tie_tolerance=0.5`); no hardcoded window-count limit.
- `deployment_windows/start.py` — replaced the hardcoded
  `OpportunitySelectionEngineConfig()` construction with
  `settings.opportunity_selection_config` (the loaded value); added the
  `--dry-run` and `--dry-run-orb-pairs` CLI flags and their fail-closed
  wiring (§6 below); `bridge_submit` is `None` when `--dry-run` is set,
  otherwise the real submission closure — unchanged for every other path.
- `deployment_windows/config/titan_protocol_config.example.json` — added
  the new `opportunity_selection_engine` section, every value equal to
  the field's own Python dataclass default, so this shipped example
  remains fully inert (P1) exactly as before this change.

**Phase B — automated tests / structural validation (§10):**
- `tests/deployment_windows/test_config_loader.py` — 13 new tests
  (`TestOpportunitySelectionEngineConfigurability`,
  `TestGateBEnabledWindowMismatchThroughTheLoader`, plus 2 more in the
  existing backward-compatibility/example-parity classes).
- `tests/deployment_windows/_fixtures.py` — added
  `opportunity_selection_engine_overrides` parameter to `write_config()`.
- `tests/titan_protocol/runtime/test_opportunity_selection_barrier.py` —
  6 new F1 regression tests
  (`TestF1BroadGateARequiresCompleteBarrierCoverage`).
- `tests/deployment_windows/test_start_dry_run.py` (new file) — 4 tests
  covering the dry-run CLI fail-closed behavior and a real subprocess
  boot proof.
- `tests/titan_protocol/bridge/test_structural_boundary.py` — extended
  `allowed_prefixes` with the 4 new Phase A/B/D paths (the 2 new example
  config files, the new test file, and `_fixtures.py`) plus this document
  itself.

**Phase C support — staged production configuration artifacts (§6 steps
2–4, prepared but not deployed to any live instance from this sandbox —
see §5 below for the honest scope caveat):**
- `deployment_windows/config/titan_protocol_config.staged_activation.example.json`
  (new) — Gate B (`opening_range_anchors`) and `enabled_windows` fully
  populated at the §1 governing values, `cross_pair_selection_enabled:
  false`, Gate A untouched (still closed in source). Represents state P2.
- `deployment_windows/config/titan_protocol_config.dry_run_activation.example.json`
  (new) — identical, except `cross_pair_selection_enabled: true` — the
  complete intended final production state, for use only with
  `--dry-run` (and, in this sandbox, `--dry-run-orb-pairs`, since no
  source redeploy of `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` occurred here).

**Documentation:**
- `deployment_windows/KNOWN_GAPS.md` — new §14 documenting the config-
  loading closure, that Gate A remaining a source constant is deliberate
  precedent (ADR-026 Hard Rule 5), and the new dry-run mechanism; states
  explicitly that no production activation is authorized by this closure.
- `deployment_windows/WINDOWS_OPERATOR_GUIDE.md` — new section covering
  Phases A–D only, with the exact dry-run CLI invocation and expected
  log output; explicitly states Phase E/F are not covered by that guide.

## 3. Configuration fingerprints

| File | SHA-256 |
|---|---|
| `titan_protocol_config.staged_activation.example.json` | `ef9c42d2ce83e8ef7b123443f6e1b2c4a09f6806ae6066f2ced3649800e5d975` |
| `titan_protocol_config.dry_run_activation.example.json` | `149b7ffb4adb8ec06dc3c0e9f216ea442906ad2a747b3b86b4da8ca323bc8ad5` |

(Both recomputed and re-confirmed unchanged immediately before this
commit via `sha256sum`.)

## 4. Tests

| Suite | Count | Result |
|---|---|---|
| `tests.deployment_windows.test_config_loader` | 59 | PASS |
| `tests.deployment_windows.test_start_dry_run` (new) | 4 | PASS |
| `tests.titan_protocol.runtime.test_opportunity_selection_barrier` | 25 (6 new F1) | PASS |
| `tests.titan_protocol.bridge.test_structural_boundary` | 5 | PASS |
| Full repo suite (`python3 -m unittest discover -s tests -t .`) | 3,381 | 3,378 PASS, 3 pre-existing environmental errors (unrelated — see below) |
| `python3 -m compileall deployment_windows titan_protocol tests` | — | clean |

**Pre-existing, unrelated environmental failures (not introduced by this
change):** `tests.test_account_snapshot`, `tests.test_journal_fields`,
`tests.test_score_signal` fail at import time with `ModuleNotFoundError:
No module named 'flask'` — they import the reference-only
`phantom_institutional.py`, which is not part of the active Titan
Protocol pipeline (CLAUDE.md §2) and has no bearing on ADR-037. Confirmed
reproducible identically on the unmodified `bb8b4a6` baseline via `git
stash` before this pass's changes were applied, and confirmed the
environment itself lacks the `flask` package (`python3 -c "import
flask"` fails the same way outside any test). Not fixed here, per the
Plan's own scope boundaries (§13/§16) and per Minimal Change Engineer
discipline — out of scope for ADR-037.

## 5. Dry-run configuration used, and an honest scope caveat on the observation

**Configuration exercised:** `titan_protocol_config.dry_run_activation.example.json`
(fingerprint above) — Gate B fully populated (LONDON 08:00, LONDON_NEW_
YORK_OVERLAP 13:00, EARLY_NEW_YORK 13:30 UTC), all 3 matching
`enabled_windows` entries (`enabled: true`), `cross_pair_selection_
enabled: true` — the complete intended final production state per §1 of
the Plan.

**Gate A for the dry run:** this sandbox has no separate "live instance"
to broaden Gate A's *source* against (Plan §6 step 5 describes broadening
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` in a *separate build* of the real
deployment). No such separate build exists to modify here, and this
implementation pass is not authorized to touch
`DEFAULT_APPROVED_PAIRS_BY_STRATEGY` at all (it remains at 0 ORB entries
throughout, verified in §7). Instead, the dry-run-only
`--dry-run-orb-pairs=EURUSD,GBPUSD,USDJPY` mechanism (§7 of the task,
implemented per §6 of this document) was used to exercise a
broadened-Gate-A *process-local override*, scoped exclusively to this one
`bridge_submit=None` subprocess, fail-closed if `--dry-run` is absent,
and never written to source or any config file. This satisfies the
task's explicit requirement for "a safe way to exercise intended Gate A
during dry run without broadening live production Gate A."

**What was directly observed via a real subprocess boot (structural/
mechanical proof, PASS criteria 1/2/3/7/8 of Plan §5):**
- Process started under `--dry-run --dry-run-orb-pairs=EURUSD,GBPUSD,USDJPY
  --foreground` and stayed up for the full observation interval with no
  uncaught exception or crash-restart (confirmed via `proc.poll() is None`
  after a 3-second wait, and in a longer ad hoc manual boot).
- `validate_profile()` reported valid at boot (log line `Trading profile
  london_conservative validated OK`) against the exact dry-run
  configuration (Gate A locally broadened to 3 pairs via the override,
  Gate B/enabled_windows/flag all at their intended final values).
- `DRY RUN MODE ACTIVE` and `dry_run_orb_pairs_override_active` appeared
  in logs, confirming the operator-visible dry-run status the task
  required.
- The Bridge HTTP server bound and listened (`Bridge HTTP service
  listening on 127.0.0.1:8787`), so EA polling/health-check behavior
  remains exercised even with submission suppressed.
- No `FAILED` or `Traceback` output anywhere in the captured combined
  stdout/stderr across two independent manual boots plus the automated
  subprocess test.
- Clean shutdown on `SIGTERM`.

**What was NOT directly observed live, and why (honest limitation, per
the task's explicit permission to substitute automated-test proof for
live-market-only proofs — §13/§14):** this sandbox has no real MT5/broker
market-data feed and cannot run a full trading-day observation window
spanning all 3 real session anchors (Plan §5's literal "at minimum, one
full trading day" requirement). Consequently, PASS criteria 4
(barrier-arbitration proof), 5 (tie-behavior proof), 6 (incomplete-scan
proof), and 9 (persisted-winner-state proof against real market data)
are **not** proven by this sandbox's live boot. They are instead proven
by the automated F1 regression suite
(`TestF1BroadGateARequiresCompleteBarrierCoverage`, §4 above), which
exercises the identical `RuntimeOrchestrator` / `OpportunitySelectionEngine`
/ `check_eligibility()` / `validate_profile()` code path with the same
configuration values (3 Gate A pairs, the same 3 Gate B anchors/enabled
windows, `tie_tolerance=0.5`) against synthetic-but-realistic per-pair
snapshots, and directly asserts: exactly one winner reaches
`CycleOutcome.SUBMITTED` with complete coverage (criterion 4, plus the
pre-existing `TestTieProducesNoWinner` for criterion 5 and
`TestIncompleteScanFailsClosed` for criterion 6); `OpportunityWinnerStore`
persistence is exercised by the pre-existing
`TestWinnerImmutabilityAcrossCycles` suite (criterion 9's mechanism).
This is exactly the substitution the task's own §13/§14 explicitly
permits, clearly distinguished here as automated-test proof rather than
live-market proof — it is **not** a substitute for the full real-market
observation window an actual production deployment with real broker
connectivity must still run before Phase E, and this document does not
claim otherwise.

**Structural-readiness cross-check (also performed directly, outside the
subprocess):** `validate_profile()` was called directly against the
dry-run configuration values: it correctly reports `valid=False` when
combined with the real (closed) Gate A ("`cross_pair_selection_enabled`
is `True` but Gate A approves only 0 ORB pair(s)" — matching state P3),
and `valid=True` when combined with a simulated 3-pair Gate A (matching
state P5) — confirming the loader and validator compose correctly with
the fingerprinted configuration independent of the subprocess mechanism.

## 6. Dry-run mechanism implemented (§6/§7 of the task)

- `start.py --dry-run`: sets `bridge_submit=None` on the
  `RuntimeOrchestrator` construction (Bridge submission structurally
  unreachable per the gate at `engine.py:422`,
  `self.bridge_submit is not None and compliance.ready_for_bridge`,
  regardless of Gate A/barrier state), and logs explicit dry-run status.
- `start.py --dry-run-orb-pairs=<comma-separated pairs>`: a dry-run-only,
  process-local override of `approved_pairs_by_strategy` for
  `StrategyId.OPENING_RANGE_BREAKOUT`, via `dataclasses.replace()` on the
  in-memory `strategy_config`. Fail-closed at three levels — inside
  `run_foreground()`, inside `launch_and_report()`, and inside `main()`'s
  argument parsing before any config is even loaded — if supplied without
  `--dry-run` (exit code 2, no process starts). Never persisted to any
  file; never touches `DEFAULT_APPROVED_PAIRS_BY_STRATEGY`; scoped to the
  one `bridge_submit=None` process (proven by
  `TestDryRunOrbPairsOverrideNeverTouchesTheRealSourceConstant`, which
  re-reads the real source constant in the *test process itself*,
  before and after the child boots, and asserts it is unaffected both
  times).
- **F3 correction carried forward:** this implementation does not add,
  and does not claim, any config-reload-without-restart capability.
  `start.py` has no `SIGHUP`/reload handler (confirmed: only
  `SIGINT`/`SIGTERM` are wired to `_handle_shutdown`); this document and
  the operator guide describe the dry run and staged config exclusively
  in terms of process restarts with a named config file, never a reload.

## 7. Post-implementation safety re-verification

Re-confirmed directly, immediately before this commit:

- `DEFAULT_APPROVED_PAIRS_BY_STRATEGY` — 0 `OPENING_RANGE_BREAKOUT` pairs
  (Gate A still closed in source).
- `titan_protocol_config.example.json`'s `opportunity_selection_engine`
  section — every value equals the Python dataclass default
  (`enabled_windows: []`, `cross_pair_selection_enabled: false`,
  `tie_tolerance: 0.5`); loading it in isolation reproduces the identical
  inert `OpportunitySelectionEngineConfig()` default.
- `StrategyId` enum — 6 members, unchanged.
- `build_default_registry()` — exactly 5 legacy strategies
  (`BosFvgStrategy`, `LiquiditySweepMssStrategy`, `RangeReversalStrategy`,
  `SessionBreakoutStrategy`, `TrendContinuationStrategy`); ORB absent,
  unchanged.
- Only the file set listed in §2 above changed
  (`git status --porcelain`); no unauthorized file touched.
- No config file in this repository other than the clearly-labeled,
  dry-run-only `titan_protocol_config.dry_run_activation.example.json`
  sets `cross_pair_selection_enabled: true`.

## 8. PASS / FAIL determination

**PASS**, against every criterion in Plan §5 / task §14 that this sandbox
can actually exercise, with the live-market-only criteria (4/5/6/9)
explicitly and honestly substituted by the automated F1 regression suite
per the task's own explicit permission (§13/§14), and that substitution
clearly distinguished from live-boot proof throughout §5 above rather
than conflated with it.

**This PASS determination does not, by itself, satisfy Plan §5's literal
full-trading-day real-market observation-window requirement** — that
remains outstanding against the actual target deployment with real
broker connectivity, and is a Phase D activity for whoever operates that
deployment, not something achievable inside this coding sandbox. Phase E
review should treat this document's automated-test substitutions as
sufficient mechanism-correctness proof, but should still require (or
explicitly waive, if it judges the automated proof sufficient) the
live-market observation window before Phase F.

## 9. Remaining authorization boundaries (restated explicitly)

Not authorized by this document or this implementation pass:
- Broadening Gate A (`DEFAULT_APPROVED_PAIRS_BY_STRATEGY`) in any running
  production deployment.
- Setting `cross_pair_selection_enabled: true` in any config file used by
  a live-submitting deployment.
- Phase E activation review/authorization.
- Phase F live activation.
- Enabling live Bridge submission for ORB.
- Retiring legacy strategies, runner-up fallback, or ADR-035 Phase 5 work.

**Phase E is not approved by this document.**

"""ProducerRunner — the autonomous demo-only orchestration layer (Phase 7A).

Wires accepted components into the exact frozen pipeline. Reimplements no
strategy, compliance, news, risk, signal-id, or bridge logic. Never places an
order; never modifies a stop (Position Manager remains the sole stop owner).
Deterministic: identical injected inputs + ``now`` -> identical decisions/ids.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.audit import AuditLog
from ..bridge.contract import PRODUCTION_INSTRUCTION_SCHEMA_VERSION
from ..bridge.paths import BridgePaths
from ..bridge.producer import write_instruction
from ..compliance import ComplianceEngine, ComplianceAuditLog
from ..compliance import sizing
from ..compliance.contract import candidate_risk_amount
from . import ingest, providers
from .bridge_health import observe_entry_bridge
from .contract import (CycleOutcome, CycleResult, RunnerConfig, RunnerMode,
                       RunnerReason, RunnerRefused, cycle_id)
from .scheduler import last_closed_open
from .state import RunnerAudit, RunnerState
from .strategy_adapter import StrategyAdapter, candidate_from_instruction


class ProducerRunner:
    def __init__(self, config, *, bridge_paths, market, account, news, broker,
                 strategy=None, state_path, runner_audit_path, compliance_audit_path,
                 kill_switch=None, strategy_by_session=None):
        if not isinstance(config, RunnerConfig):
            raise TypeError("config must be a RunnerConfig")
        self.config = config
        self.paths = bridge_paths if isinstance(bridge_paths, BridgePaths) else BridgePaths(bridge_paths)
        self.market = market
        self.account = account
        self.news = news
        self.broker = broker
        # A single injected strategy is the legacy/London adapter; a per-session map
        # (PR-4A, from wiring) provides one session-configured adapter per profile.
        self.strategy = (None if strategy is None
                         else strategy if isinstance(strategy, StrategyAdapter)
                         else StrategyAdapter(strategy))
        self._strategy_by_session = {
            sid: (a if isinstance(a, StrategyAdapter) else StrategyAdapter(a))
            for sid, a in (strategy_by_session or {}).items()
        }
        # Enabled session profiles the cycle fans out over. Empty config -> a single
        # implicit LONDON profile (the frozen engine's default session).
        from ..session.profiles import profile_for
        self._profiles = (tuple(config.session_profiles)
                          or (profile_for("LONDON"),))
        self.state = RunnerState(state_path)
        self.audit = RunnerAudit(runner_audit_path)
        self.bridge_audit = AuditLog(self.paths.audit_log)
        self.compliance = ComplianceEngine(
            config=config.compliance,
            audit_log=ComplianceAuditLog(compliance_audit_path),
            bridge_writer=None)                 # runner writes the FULL strategy instruction
        self._kill_switch = kill_switch or (lambda now: False)
        self._last_error = None

    # -- demo / FTMO safety (no override can bypass) -------------------------
    def preflight(self, now):
        cfg = self.config
        if cfg.mode != RunnerMode.DEMO:
            raise RunnerRefused("mode is not DEMO (this phase is demo-only)")
        if not cfg.ftmo_profile_verified:
            raise RunnerRefused("FTMO profile is unverified")
        # Phase 8C: the compliance FTMO profile itself must be verified/usable.
        perr = cfg.compliance.profile.verification_error()
        if perr is not None:
            raise RunnerRefused(f"FTMO profile not usable: {perr}")
        acct = self.account.snapshot(now)
        if not isinstance(acct, dict):
            raise RunnerRefused("account snapshot unavailable")
        if acct.get("is_demo") is not True or acct.get("account_type") != "DEMO":
            raise RunnerRefused("account not verified as DEMO")
        if acct.get("terminal_connected") is None:
            raise RunnerRefused("MT5 connection state unknown")
        return True

    # -- one deterministic cycle -------------------------------------------
    def run_cycle(self, now):
        cfg = self.config
        results = []

        # 1. service health + kill switch
        if bool(self._kill_switch(now)):
            results.append(self._emit(CycleOutcome.KILL_SWITCH, "-", "-",
                                      [RunnerReason.KILL_SWITCH], now, {}))
            return results

        # 4/5 (cycle-scoped snapshots): account + news obtained once per cycle
        acct = self.account.snapshot(now)
        ok_acct, acct_reason = providers.validate_account(acct, now, cfg.max_account_age_sec)
        demo_ok = (isinstance(acct, dict) and acct.get("is_demo") is True
                   and acct.get("account_type") == "DEMO")
        if not ok_acct or not demo_ok:
            reason = acct_reason if not ok_acct else RunnerReason.ACCOUNT_UNAVAILABLE
            for sym in cfg.symbols:
                results.append(self._emit(CycleOutcome.ACCOUNT_REJECTED, sym, "-",
                                          [reason], now, {"demo_ok": demo_ok}))
            return results
        news_bundle = self.news.bundle(now)     # compliance validates it (fails closed)

        # Phase 9A: one canonical session snapshot per cycle (deterministic) — used
        # for AUDIT/CONTEXT only. The per-session STRATEGY entry window (not the
        # coarse market-session window) is the trading authority (SC-2 resolution).
        sess = None
        if cfg.session_model is not None:
            from ..session.model import session_snapshot
            sess = session_snapshot(cfg.session_model, now, cfg.strategy_capability)
        self._last_session_snapshot = sess

        # Fan out: bars are fetched/validated once per symbol (session-independent),
        # then each enabled session profile is evaluated INDEPENDENTLY on those bars.
        # M3: each symbol and each session is fault-isolated — one deterministic
        # exception fails ONLY that unit (fail-closed, no instruction written, no
        # capacity reserved) and never starves sibling symbols/sessions. Global
        # prerequisites (kill/account/news above) already gate the whole cycle, so
        # isolation applies only after those succeed. End-of-cycle reconciliation
        # ALWAYS runs (finally) so a local fault cannot suppress result ingestion.
        try:
            for sym in cfg.symbols:
                try:
                    prepared = self._prepare_symbol(sym, now)
                except Exception as exc:               # symbol-level prep fault -> skip symbol
                    results.append(self._unit_error(sym, "-", now, "prepare_symbol", exc))
                    continue
                if isinstance(prepared, CycleResult):
                    results.append(prepared)
                    continue
                exec_bars, bar_iso, versions = prepared
                for profile in self._profiles:
                    try:
                        results.append(self._run_symbol_session(
                            sym, profile, now, acct, news_bundle, exec_bars, bar_iso, versions))
                    except Exception as exc:           # session-local fault -> skip session
                        results.append(self._unit_error(sym, profile.session_id, now,
                                                        "run_symbol_session", exc))
        finally:
            # 11/12. result ingestion + reconciliation (read-only) MUST run even if a
            # symbol/session unit faulted above (M3 §26).
            try:
                self._ingest_and_reconcile(now)
            except Exception as exc:
                self._last_error = repr(exc)
        return results

    def _unit_error(self, symbol, session_id, now, stage, exc):
        """Emit a fail-closed isolated-unit error result (no instruction written, no
        capacity reserved). Diagnostics identify the symbol/session/stage; the
        exception type is recorded (no secrets)."""
        return self._emit(CycleOutcome.UNIT_ERROR, symbol, "-", [RunnerReason.UNIT_ERROR],
                          now, {}, detail={"session_id": session_id, "stage": stage,
                                           "error": type(exc).__name__})

    def _observe_bridge(self, now):
        """ONE read-only entry-bridge snapshot (H5) feeding capacity reservation, ACK
        liveness (missing_ack_count) and bridge health (bridge_healthy). Fails closed."""
        return observe_entry_bridge(self.paths, now)

    def _effective_account_state(self, acct, obs):
        """Broker account snapshot (immutable) with open_position_count / open_symbols
        RAISED by the OUTSTANDING entry intents in the bridge observation, so
        compliance's existing max_open_positions and one_position_per_symbol gates
        account for unfilled orders (MS-2). Broker truth is never mutated — a shallow
        copy carries the effective view."""
        eff = dict(acct)
        broker_open = acct.get("open_position_count")
        if isinstance(broker_open, int) and not isinstance(broker_open, bool):
            eff["open_position_count"] = broker_open + int(obs.outstanding_count)
        broker_syms = acct.get("open_symbols") or ()
        eff["open_symbols"] = tuple(set(broker_syms) | set(obs.outstanding_symbols))
        # H-1: aggregate committed ACCOUNT RISK before this candidate = worst-case open-
        # position downside + DECLARED risk of all outstanding intents (pending+claimed,
        # which — because each authorized instruction is written to pending BEFORE the
        # next candidate is observed — already INCLUDES same-cycle authorized candidates
        # and survives restart). The compliance gate subtracts this (plus the current
        # candidate's own risk) from equity in the daily/static projection. Plumbing
        # only: the runner never decides FTMO eligibility, it only reserves. Any
        # unverifiable component (unhealthy bridge, unreadable outstanding risk, or an
        # unquantifiable open position) sets committed_risk_at_stop=None so the gate
        # FAILS CLOSED — never a silent zero.
        from ..compliance.contract import finite
        initial = finite(getattr(self.config.compliance.profile, "initial_balance", None))
        open_risk = acct.get("open_risk_at_stop")
        open_risk = finite(open_risk) if open_risk is not None else None
        if (not obs.healthy or obs.outstanding_risk_unverifiable
                or acct.get("open_risk_unverifiable") or initial is None or open_risk is None):
            eff["committed_risk_at_stop"] = None
            eff["committed_risk_unverifiable"] = True
        else:
            eff["committed_risk_at_stop"] = open_risk + float(obs.outstanding_risk_fraction) * initial
            eff["committed_risk_unverifiable"] = False
        return eff

    def _size_volume(self, candidate, bh):
        """M9 sizing authority: the largest step-aligned lot whose monetary loss-at-stop
        stays within the risk-per-trade budget (risk_fraction × initial_balance), using
        broker tick/volume metadata. Returns None (=> compliance fails closed, no trade)
        when metadata is missing or the budget cannot fund the minimum lot. This is the
        SAME risk primitive compliance uses to re-prove risk, so sizer and gate agree."""
        permitted = candidate_risk_amount(candidate, self.config.compliance.profile)
        if permitted is None:
            return None
        return sizing.allowable_volume(
            candidate.get("entry"), candidate.get("stop_loss"), permitted,
            bh.get("tick_size"), bh.get("tick_value"),
            bh.get("volume_min"), bh.get("volume_max"), bh.get("volume_step"))

    def _sizing_diagnostics(self, candidate, bh, final_volume):
        """Explainable, deterministic sizing breakdown for the audit — 'why this
        volume?'. Read-only: it recomputes the same PR-3J inputs for transparency and
        NEVER makes a second sizing decision (``final_volume`` is PR-3J's output).
        No account identity/secret is exposed (only the capital BASIS amount)."""
        from ..compliance.contract import finite
        profile = self.config.compliance.profile
        rf = finite(candidate.get("risk_fraction"))
        basis = finite(getattr(profile, "initial_balance", None))   # pinned funded capital
        permitted = candidate_risk_amount(candidate, profile)       # rf * initial_balance
        d = sizing.price_distance(candidate.get("entry"), candidate.get("stop_loss"))
        raw = None
        ts, tv = finite(bh.get("tick_size")), finite(bh.get("tick_value"))
        if permitted is not None and d is not None and ts and tv:
            per_lot = d / ts * tv
            raw = (permitted / per_lot) if per_lot > 0 else None
        loss = sizing.loss_at_stop(candidate.get("entry"), candidate.get("stop_loss"),
                                   final_volume, ts, tv) if final_volume else None
        return {
            "authority": "PR-3J compliance.sizing.allowable_volume",
            "sizing_mode": getattr(self.config, "sizing_mode", None),
            "capital_basis": basis,                 # pinned initial_balance (not live equity)
            "risk_fraction": rf,
            "risk_amount": permitted,               # basis * risk_fraction
            "stop_distance": d,
            "tick_size": ts, "tick_value": tv,
            "volume_min": bh.get("volume_min"), "volume_max": bh.get("volume_max"),
            "volume_step": bh.get("volume_step"),
            "raw_volume": raw,                      # pre-rounding (illustrative)
            "final_volume": final_volume,           # PR-3J step-rounded, budget-proven
            "loss_at_stop_final": loss,
        }

    def _session_trade_eligible(self, profile, now):
        """Per-session entry eligibility (PR-4A). Authority = the session's STRATEGY
        entry window (SC-2), then the configured OVERLAP_MODE from the session model:
        ALLOW/DISABLE trade each session independently; REQUIRE permits a session only
        while it is a member of an active enabled market overlap. Returns
        (ok, reason_code_or_None)."""
        if not profile.is_within_strategy_window(now):
            return False, None
        # M12: at/after this session's Friday no-new-entry cutoff (session-local,
        # DST-aware), NO new entry may be authorized. Open positions are still managed
        # by the position manager (a separate service) — this gate blocks ENTRY only.
        if profile.is_friday_no_new_entry(now):
            return False, RunnerReason.FRIDAY_NO_NEW_ENTRY
        model = self.config.session_model
        if model is not None and getattr(model, "overlap_mode", None) == "REQUIRE":
            from ..session.model import OVERLAPS, SessionReason, active_overlaps
            act = active_overlaps(model, now)
            if not any(profile.session_id in OVERLAPS[o] for o in act):
                return False, (SessionReason.OVERLAP_REQUIRED if model.enabled_overlaps
                               else SessionReason.OVERLAP_NOT_ENABLED)
        return True, None

    def _adapter_for(self, profile):
        """Resolve the session-configured strategy adapter for ``profile``. A
        per-session map wins; otherwise the single injected strategy serves LONDON
        (legacy). Returns None -> that session fails closed (no adapter)."""
        a = self._strategy_by_session.get(profile.session_id)
        if a is not None:
            return a
        if profile.session_id == "LONDON":
            return self.strategy
        return None

    # -- per-symbol bar preparation (session-independent) -------------------
    def _prepare_symbol(self, symbol, now):
        """Fetch + validate bars for a symbol once (session-independent). Returns
        (exec_bars, bar_iso, versions) or a terminal CycleResult on data failure."""
        cfg = self.config
        tf_bars = {}
        versions = {}
        for tf in cfg.required_timeframes:
            b = self.market.get_bars(symbol, tf, now)
            min_bars = cfg.strategy_config.get("min_history_bars", 60) if tf == cfg.exec_timeframe else 2
            okb, rb = providers.validate_bars(b, tf, now, cfg.max_data_age_sec,
                                              cfg.continuity_bars, min_bars)
            if not okb:
                return self._emit(CycleOutcome.DATA_REJECTED, symbol, "-", [rb], now, {"tf": tf})
            tf_bars[tf] = b
            versions[tf] = b.version()

        exec_bars = tf_bars[cfg.exec_timeframe]
        bar_iso = serialize.iso_utc(exec_bars.last["open_time"])
        # the just-closed exec bar must be the schedule's latest closed bar
        if exec_bars.last["open_time"] != last_closed_open(now, cfg.exec_timeframe):
            return self._emit(CycleOutcome.DATA_REJECTED, symbol, bar_iso,
                              [RunnerReason.DATA_STALE], now, versions)
        return exec_bars, bar_iso, versions

    # -- per-(symbol, session) pipeline ------------------------------------
    def _run_symbol_session(self, symbol, profile, now, acct, news_bundle,
                            exec_bars, bar_iso, versions):
        """Evaluate ONE session profile for a symbol on the prepared bars. State is
        keyed by (symbol, session) so each session processes the bar independently."""
        sid_state = "{}|{}".format(symbol, profile.session_id)
        detail = {"session_id": profile.session_id}

        # 13 (guard): same bar not evaluated twice for THIS session / no restart dup
        if self.state.get_last(sid_state) == bar_iso:
            return self._emit(CycleOutcome.NO_NEW_BAR, symbol, bar_iso,
                              [RunnerReason.NO_NEW_BAR], now, versions, detail=detail)

        # per-session eligibility: the STRATEGY entry window (SC-2: NOT the coarse
        # market close) plus the configured OVERLAP_MODE. If ineligible, do not
        # evaluate the engine for this session — deterministic no-trade audit.
        elig_ok, elig_reason = self._session_trade_eligible(profile, now)
        if not elig_ok:
            self.state.mark_processed(sid_state, bar_iso)
            codes = [RunnerReason.SESSION_INELIGIBLE]
            if elig_reason is not None:
                codes.append(elig_reason)
            return self._emit(CycleOutcome.SESSION_INELIGIBLE, symbol, bar_iso,
                              codes, now, versions, detail=detail)

        adapter = self._adapter_for(profile)
        if adapter is None:                       # advertised session without an engine
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.SESSION_INELIGIBLE, symbol, bar_iso,
                              [RunnerReason.SESSION_INELIGIBLE], now, versions,
                              detail={**detail, "no_adapter": True})

        # 6. deterministic strategy evaluation (frozen engine; no duplication)
        instr = adapter.evaluate(symbol, exec_bars)

        # 7. no candidate -> audit, no bridge write
        if instr is None:
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.NO_CANDIDATE, symbol, bar_iso,
                              [RunnerReason.NO_CANDIDATE], now, versions, detail=detail)

        # session identity must be present and match the profile (fail closed)
        if instr.get("session_id") != profile.session_id:
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.NO_CANDIDATE, symbol, bar_iso,
                              [RunnerReason.NO_CANDIDATE], now, versions,
                              detail={**detail, "session_mismatch": instr.get("session_id")})

        candidate = candidate_from_instruction(instr)
        sid = instr["signal_id"]

        # 8. dedup FIRST (exactly-once): a signal already anywhere in the bridge is an
        # idempotent replay (e.g. restart re-emitting the same bar) — suppress it here,
        # BEFORE compliance/capacity reservation, so a signal never counts ITSELF in
        # the outstanding-intent reservation and a known duplicate needs no re-decision.
        if ingest.already_seen(self.paths, sid):
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.DUPLICATE_SUPPRESSED, symbol, bar_iso,
                              [RunnerReason.DUPLICATE_SUPPRESSED], now, versions,
                              signal_id=sid, detail=detail)

        # 9. mandatory FTMO compliance (component is the only authority; GLOBAL).
        # MS-2: reserve account capacity for OUTSTANDING ENTRY INTENTS (instructions
        # written but not yet filled/terminal — same cycle AND prior cycles/restart)
        # so multi-session/multi-symbol fan-out cannot exceed max_open_positions or
        # one-position-per-symbol before MT5 reflects the fills. Broker truth stays
        # immutable; the effective count/symbols are what compliance checks (single
        # place, no duplicated max-position arithmetic).
        bh = self.broker.snapshot(symbol, now) or {}
        market_state = {"symbol_tradable": bh.get("symbol_tradable"),
                        "market_open": bh.get("market_open")}
        # H5: overlay AUTHORITATIVE bridge liveness onto the broker-health facts the
        # compliance gate consumes (the MT5 provider's placeholders are replaced with
        # the real entry-bridge observation). One snapshot feeds capacity + liveness.
        obs = self._observe_bridge(now)
        bh = {**bh, "bridge_healthy": obs.healthy,
              "missing_ack_count": obs.missing_ack_count}
        eff_acct = self._effective_account_state(acct, obs)

        # M9: SIZING AUTHORITY. Compute the ONE authoritative execution volume from the
        # approved entry/stop geometry, the risk-per-trade budget (risk_fraction ×
        # initial_balance), and broker symbol tick/volume metadata — then FINALIZE the
        # engine's pre-sizing proto-instruction (schema 2) to the on-wire production
        # schema (3) by attaching that volume. Compliance re-proves the resulting
        # monetary loss-at-stop from this exact volume; the EA executes it verbatim.
        # A None volume (missing metadata, or risk budget below the minimum lot) flows
        # to compliance, which fails closed (RISK_MONETARY_UNVERIFIABLE) — no trade,
        # never an independent EA lot.
        # User risk-profile POLICY: stamp the configured per-trade risk cap onto BOTH
        # the instruction and the candidate BEFORE sizing/compliance/write, so PR-3J
        # sizing, the compliance RISK re-proof, and H-1 committed-risk accounting all
        # use the SAME risk_fraction (one authority). None -> keep the engine's own
        # risk_fraction (backward compatible). This is a risk CAP only; it changes no
        # signal, geometry, session, news, or FTMO logic.
        prf = getattr(self.config, "policy_risk_fraction", None)
        if prf is not None:
            instr = {**instr, "risk_fraction": prf}
            candidate = {**candidate, "risk_fraction": prf}

        volume = self._size_volume(candidate, bh)
        instr = {**instr, "volume": volume,
                 "schema_version": PRODUCTION_INSTRUCTION_SCHEMA_VERSION}
        candidate = {**candidate, "volume": volume}
        # Explainable sizing diagnostics (audit only; NOT a second decision — PR-3J
        # already produced `volume`). Answers "why this volume?" deterministically.
        detail["sizing"] = self._sizing_diagnostics(candidate, bh, volume)

        decision = self.compliance.evaluate(
            candidate, market_state=market_state, account_state=eff_acct,
            broker_health=bh, news_bundle=news_bundle, now=now,
            kill_switch=False, dry_run=False)

        # 10. compliance reject -> audit, no bridge write
        if not decision.is_pass:
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(
                CycleOutcome.COMPLIANCE_REJECT, symbol, bar_iso,
                [RunnerReason.COMPLIANCE_REJECT, *decision.reason_codes], now,
                versions, signal_id=candidate["signal_id"],
                compliance_decision_id=decision.decision_id, detail=detail)

        # 11. compliance pass -> write. The write lands the instruction in pending/,
        # so the very next candidate's bridge observation reserves this slot+symbol
        # (MS-2), same cycle.
        write_instruction(self.paths, instr, now, audit=self.bridge_audit)
        self.state.mark_written(sid)
        self.state.mark_processed(sid_state, bar_iso)
        return self._emit(CycleOutcome.INSTRUCTION_WRITTEN, symbol, bar_iso,
                          [RunnerReason.INSTRUCTION_WRITTEN], now, versions,
                          signal_id=sid, compliance_decision_id=decision.decision_id,
                          detail=detail)

    # -- ingestion / reconciliation ----------------------------------------
    def _ingest_and_reconcile(self, now):
        statuses = ingest.ingest(self.paths, list(self.state.written_signals))
        for sid, st in statuses.items():
            if st["reconcile_required"]:
                self.audit.emit({
                    "kind": "reconcile", "timestamp": serialize.iso_utc(now),
                    "signal_id": sid, "reason_code": RunnerReason.RECONCILE_REQUIRED,
                    "status": st})
        return statuses

    # -- audit + result construction ---------------------------------------
    def _emit(self, outcome, symbol, bar_ts, reason_codes, now, versions,
              signal_id=None, compliance_decision_id=None, session=None, detail=None):
        now_iso = serialize.iso_utc(now)
        cid = cycle_id(symbol, bar_ts, now_iso, versions)
        sess = session if session is not None else getattr(self, "_last_session_snapshot", None)
        detail = dict(detail or {})
        record = {
            "kind": "cycle",
            "cycle_id": cid,
            "timestamp": now_iso,
            "symbol": symbol,
            "session_id": detail.get("session_id"),      # PR-4A: first-class in audit
            "bar_ts": bar_ts,
            "outcome": outcome,
            "reason_codes": list(reason_codes),
            "signal_id": signal_id,
            "compliance_decision_id": compliance_decision_id,
            "data_versions": versions,
            # Phase 9A: deterministic session audit fields (None when no session model)
            "session": None if sess is None else {
                "config_version": sess.get("config_version"),
                "enabled_sessions": sess.get("enabled_sessions"),
                "enabled_overlaps": sess.get("enabled_overlaps"),
                "overlap_mode": sess.get("overlap_mode"),
                "active_sessions": sess.get("active_sessions"),
                "active_overlaps": sess.get("active_overlaps"),
                "eligible": sess.get("eligible"),
                "eligibility_reason": sess.get("eligibility_reason"),
                "strategy_supported": sess.get("strategy_supported"),
                "snapshot_id": sess.get("snapshot_id"),
            },
        }
        self.audit.emit(record)
        return CycleResult(cid, symbol, bar_ts, outcome, tuple(reason_codes),
                           signal_id, compliance_decision_id,
                           {"versions": versions, **detail})

    # -- status snapshot pass-through --------------------------------------
    @property
    def last_error(self):
        return self._last_error

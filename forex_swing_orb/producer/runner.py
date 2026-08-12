"""ProducerRunner — the autonomous demo-only orchestration layer (Phase 7A).

Wires accepted components into the exact frozen pipeline. Reimplements no
strategy, compliance, news, risk, signal-id, or bridge logic. Never places an
order; never modifies a stop (Position Manager remains the sole stop owner).
Deterministic: identical injected inputs + ``now`` -> identical decisions/ids.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.audit import AuditLog
from ..bridge.paths import BridgePaths
from ..bridge.producer import write_instruction
from ..compliance import ComplianceEngine, ComplianceAuditLog
from . import ingest, providers
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

        # symbols for which THIS cycle already wrote an instruction — enforces
        # one-position-per-symbol ACROSS sessions before any position is open (§18).
        self._cycle_claimed_symbols = set()

        # Fan out: bars are fetched/validated once per symbol (session-independent),
        # then each enabled session profile is evaluated INDEPENDENTLY on those bars.
        for sym in cfg.symbols:
            prepared = self._prepare_symbol(sym, now)
            if isinstance(prepared, CycleResult):
                results.append(prepared)
                continue
            exec_bars, bar_iso, versions = prepared
            for profile in self._profiles:
                results.append(self._run_symbol_session(
                    sym, profile, now, acct, news_bundle, exec_bars, bar_iso, versions))

        # 11/12. result ingestion + reconciliation (read-only)
        self._ingest_and_reconcile(now)
        return results

    def _session_trade_eligible(self, profile, now):
        """Per-session entry eligibility (PR-4A). Authority = the session's STRATEGY
        entry window (SC-2), then the configured OVERLAP_MODE from the session model:
        ALLOW/DISABLE trade each session independently; REQUIRE permits a session only
        while it is a member of an active enabled market overlap. Returns
        (ok, reason_code_or_None)."""
        if not profile.is_within_strategy_window(now):
            return False, None
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

        # 8. mandatory FTMO compliance (component is the only authority; GLOBAL)
        candidate = candidate_from_instruction(instr)
        bh = self.broker.snapshot(symbol, now) or {}
        market_state = {"symbol_tradable": bh.get("symbol_tradable"),
                        "market_open": bh.get("market_open")}
        decision = self.compliance.evaluate(
            candidate, market_state=market_state, account_state=acct,
            broker_health=bh, news_bundle=news_bundle, now=now,
            kill_switch=False, dry_run=False)

        # 9. compliance reject -> audit, no bridge write
        if not decision.is_pass:
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(
                CycleOutcome.COMPLIANCE_REJECT, symbol, bar_iso,
                [RunnerReason.COMPLIANCE_REJECT, *decision.reason_codes], now,
                versions, signal_id=candidate["signal_id"],
                compliance_decision_id=decision.decision_id, detail=detail)

        # cross-session same-symbol guard (§18/§27): one-position-per-symbol is
        # account-GLOBAL. If an earlier session already claimed this symbol THIS
        # cycle, suppress the later session (session identity never multiplies
        # account exposure). Global compliance still guards across cycles.
        one_per_symbol = getattr(self.config.compliance.ftmo, "one_position_per_symbol", True)
        if one_per_symbol and symbol in getattr(self, "_cycle_claimed_symbols", set()):
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.COMPLIANCE_REJECT, symbol, bar_iso,
                              [RunnerReason.COMPLIANCE_REJECT,
                               RunnerReason.SESSION_SYMBOL_CLAIMED], now, versions,
                              signal_id=candidate["signal_id"],
                              compliance_decision_id=decision.decision_id, detail=detail)

        # 10. compliance pass -> dedup guard, then write the FULL engine instruction
        sid = instr["signal_id"]
        if ingest.already_seen(self.paths, sid):
            self.state.mark_processed(sid_state, bar_iso)
            return self._emit(CycleOutcome.DUPLICATE_SUPPRESSED, symbol, bar_iso,
                              [RunnerReason.DUPLICATE_SUPPRESSED], now, versions,
                              signal_id=sid, compliance_decision_id=decision.decision_id,
                              detail=detail)
        write_instruction(self.paths, instr, now, audit=self.bridge_audit)
        self.state.mark_written(sid)
        self._cycle_claimed_symbols.add(symbol)
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

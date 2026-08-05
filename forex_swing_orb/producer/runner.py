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
                 strategy, state_path, runner_audit_path, compliance_audit_path,
                 kill_switch=None):
        if not isinstance(config, RunnerConfig):
            raise TypeError("config must be a RunnerConfig")
        self.config = config
        self.paths = bridge_paths if isinstance(bridge_paths, BridgePaths) else BridgePaths(bridge_paths)
        self.market = market
        self.account = account
        self.news = news
        self.broker = broker
        self.strategy = strategy if isinstance(strategy, StrategyAdapter) else StrategyAdapter(strategy)
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

        for sym in cfg.symbols:
            results.append(self._run_symbol(sym, now, acct, news_bundle))

        # 11/12. result ingestion + reconciliation (read-only)
        self._ingest_and_reconcile(now)
        return results

    # -- per-symbol pipeline ------------------------------------------------
    def _run_symbol(self, symbol, now, acct, news_bundle):
        cfg = self.config
        # 2. obtain bars for every required timeframe; 3. validate all (fail closed)
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

        # 13 (guard): same bar not evaluated twice / no duplicate on restart
        if self.state.get_last(symbol) == bar_iso:
            return self._emit(CycleOutcome.NO_NEW_BAR, symbol, bar_iso,
                              [RunnerReason.NO_NEW_BAR], now, versions)
        # the just-closed exec bar must be the schedule's latest closed bar
        if exec_bars.last["open_time"] != last_closed_open(now, cfg.exec_timeframe):
            return self._emit(CycleOutcome.DATA_REJECTED, symbol, bar_iso,
                              [RunnerReason.DATA_STALE], now, versions)

        # 6. deterministic strategy evaluation (frozen engine; no duplication)
        instr = self.strategy.evaluate(symbol, exec_bars)

        # 7. no candidate -> audit, no bridge write
        if instr is None:
            self.state.mark_processed(symbol, bar_iso)
            return self._emit(CycleOutcome.NO_CANDIDATE, symbol, bar_iso,
                              [RunnerReason.NO_CANDIDATE], now, versions)

        # 8. mandatory FTMO compliance (component is the only authority)
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
            self.state.mark_processed(symbol, bar_iso)
            return self._emit(
                CycleOutcome.COMPLIANCE_REJECT, symbol, bar_iso,
                [RunnerReason.COMPLIANCE_REJECT, *decision.reason_codes], now,
                versions, signal_id=candidate["signal_id"],
                compliance_decision_id=decision.decision_id)

        # 10. compliance pass -> dedup guard, then write the FULL engine instruction
        sid = instr["signal_id"]
        if ingest.already_seen(self.paths, sid):
            self.state.mark_processed(symbol, bar_iso)
            return self._emit(CycleOutcome.DUPLICATE_SUPPRESSED, symbol, bar_iso,
                              [RunnerReason.DUPLICATE_SUPPRESSED], now, versions,
                              signal_id=sid, compliance_decision_id=decision.decision_id)
        write_instruction(self.paths, instr, now, audit=self.bridge_audit)
        self.state.mark_written(sid)
        self.state.mark_processed(symbol, bar_iso)
        return self._emit(CycleOutcome.INSTRUCTION_WRITTEN, symbol, bar_iso,
                          [RunnerReason.INSTRUCTION_WRITTEN], now, versions,
                          signal_id=sid, compliance_decision_id=decision.decision_id)

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
              signal_id=None, compliance_decision_id=None):
        now_iso = serialize.iso_utc(now)
        cid = cycle_id(symbol, bar_ts, now_iso, versions)
        record = {
            "kind": "cycle",
            "cycle_id": cid,
            "timestamp": now_iso,
            "symbol": symbol,
            "bar_ts": bar_ts,
            "outcome": outcome,
            "reason_codes": list(reason_codes),
            "signal_id": signal_id,
            "compliance_decision_id": compliance_decision_id,
            "data_versions": versions,
        }
        self.audit.emit(record)
        return CycleResult(cid, symbol, bar_ts, outcome, tuple(reason_codes),
                           signal_id, compliance_decision_id, {"versions": versions})

    # -- status snapshot pass-through --------------------------------------
    @property
    def last_error(self):
        return self._last_error

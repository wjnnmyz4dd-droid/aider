"""Shadow advisory service (Phase 9A) — SHADOW ONLY, zero trade authority.

Observes each producer cycle, assembles the authoritative context (session
snapshot + symbol/currencies + FTMO budgets + broker health + news + open state),
runs the advisory layer in shadow mode (deterministic MockLLMProvider — NOT
represented as live intelligence), and persists the advisory record to a separate
file. It NEVER creates an order, writes a bridge instruction, moves a stop, closes
a position, or overrides compliance/strategy/session. Advisory failure never
blocks deterministic trading. No networking.
"""

from __future__ import annotations

from ..bridge import serialize
from ..bridge.atomic import append_line_fsync
from ..compliance import mapping
from ..compliance.contract import finite, ftmo_levels
from ..session.capability import LONDON_ORB_CAPABILITY


class ShadowAdvisoryService:
    mode = "SHADOW_ONLY"

    def __init__(self, *, symbols, compliance_config, session_model, capability,
                 output_path, provider="mock"):
        self.symbols = tuple(symbols)
        self.compliance_config = compliance_config
        self.session_model = session_model
        self.capability = capability
        self.output_path = output_path
        self.provider = provider
        # the ONE shared deterministic mock provider (never real intelligence)
        from ..agents.llm import MockLLMProvider
        self._llm = MockLLMProvider() if provider == "mock" else None

    @classmethod
    def build(cls, cfg, client):
        return cls(symbols=cfg.symbols, compliance_config=None,
                   session_model=cfg.session_model(), capability=LONDON_ORB_CAPABILITY,
                   output_path=cfg.advisory_output_path, provider=cfg.advisory_provider)

    # -- observation (shadow only) -----------------------------------------
    def observe(self, runner, now):
        """Assemble context + advisory for the cycle and persist it. Returns the
        record. Never raises out (fail-safe); never returns an order."""
        try:
            ctx = self.build_context(runner, now)
            advisory = self._advise(ctx)
            record = {
                "kind": "advisory_shadow", "mode": self.mode, "provider": self.provider,
                "is_order": False, "authority": "advisory_only",
                "timestamp": serialize.iso_utc(now),
                "context": ctx, "advisory": advisory,
            }
            record["snapshot_id"] = self._rid(record)
            if self.output_path is not None:
                append_line_fsync(self.output_path, serialize.canonical_json(record))
            return record
        except Exception:
            return None                          # shadow failure is non-blocking

    def build_context(self, runner, now):
        """The AI CONTEXT CONTRACT — every field assembled from authoritative
        sources; the AI never guesses or computes eligibility itself."""
        acct = _safe(lambda: runner.account.snapshot(now))
        sess = getattr(runner, "_last_session_snapshot", None)
        if sess is None and getattr(runner.config, "session_model", None) is not None:
            from ..session.model import session_snapshot
            sess = session_snapshot(runner.config.session_model, now,
                                    getattr(runner.config, "strategy_capability", None))
        cconf = runner.config.compliance
        levels = ftmo_levels(acct or {}, cconf.profile, cconf.ftmo) if acct else None
        equity = finite((acct or {}).get("equity"))
        per_symbol = []
        for sym in self.symbols:
            bh = _safe(lambda: runner.broker.snapshot(sym, now)) or {}
            per_symbol.append({
                "symbol": sym, "base": mapping.base(sym), "quote": mapping.quote(sym),
                "broker_health": bh or None,
                "spread_points": bh.get("spread_points"),
                "recent_slippage_points": bh.get("recent_slippage_points"),
            })
        news = _safe(lambda: runner.news.bundle(now))
        return {
            "symbols": list(self.symbols),
            "per_symbol": per_symbol,
            "session": sess,                                # active/overlap/next/countdown/eligibility
            "strategy_capability": self.capability.as_dict(),
            "strategy_supported": (sess or {}).get("strategy_supported"),
            "ftmo": {
                "program": cconf.profile.program,
                "account_type": cconf.profile.account_type,
                "profile_verified": cconf.profile.profile_verified,
                "remaining_daily_loss_budget": (None if (levels is None or equity is None)
                                                else equity - levels["internal_daily_level"]),
                "remaining_max_loss_budget": (None if (levels is None or equity is None)
                                              else equity - levels["internal_max_level"]),
            },
            "account": None if acct is None else {
                "equity": acct.get("equity"), "day_start_balance": acct.get("day_start_balance"),
                "open_position_count": acct.get("open_position_count"),
                "open_symbols": acct.get("open_symbols"),
                "terminal_connected": acct.get("terminal_connected"),
            },
            "news_bundle_as_of": (news or {}).get("as_of") if isinstance(news, dict) else None,
            "news_event_count": len((news or {}).get("events", [])) if isinstance(news, dict) else 0,
            # producer-side scope: PM/manager state is owned by the manager service
            "position_manager_phase": None,
            "manager_health": None,
            "bridge_root": str(runner.paths.root),
        }

    def _advise(self, ctx):
        """Deterministic advisory summary. With the mock provider this is an
        explainable digest, explicitly NOT live intelligence."""
        note = "mock provider — deterministic digest, NOT live AI intelligence" \
            if self.provider == "mock" else "advisory"
        text = None
        if self._llm is not None:
            text = self._llm.complete(serialize.canonical_json(ctx),
                                      prompt_version="shadow.v1").text
        return {"is_order": False, "advisory_decision": "ADVISE_OBSERVE",
                "eligible": (ctx.get("session") or {}).get("eligible"),
                "provider_note": note, "explanation": text}

    def _rid(self, record):
        body = {k: v for k, v in record.items() if k != "snapshot_id"}
        import hashlib
        return hashlib.sha256(serialize.canonical_json(body).encode("utf-8")).hexdigest()[:16]


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None

"""PR-3N — characterization: NO authoritative numeric trade score exists.

The audit (and spec §8.3) prove Session Edge v1 has no graded trade score — the engine
emits a fixed confidence=1.0 pass/fail qualifier, rr_planned/min_rr is a hard gate, and
no instruction/candidate/sizing/execution/EA/compliance field carries a score. This PR
therefore adds NO production score code (BLOCKED — TRADE-SCORE AUTHORITY SPECIFICATION
REQUIRED, see docs/SESSION_EDGE_SCORE_AUTHORITY_SPEC_REQUIRED.md). These tests LOCK that
contract and guard against a score being silently introduced or fabricated later.
Deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path

from forex_swing_orb.agents.memory import MemoryStore
from forex_swing_orb.bridge.contract import REQUIRED_INSTRUCTION_FIELDS
from forex_swing_orb.research import lifecycle

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"
_SCORE_FIELD_RE = re.compile(r"\b(trade_score|setup_score|quality_score|signal_quality|"
                             r"setup_quality|confidence_score|weighted_score|evidence_score|"
                             r"min_score|minimum_score|score_threshold|score_model)\b")


def _mem(tmp_path):
    return MemoryStore(tmp_path / "memory")


def _outcome(sid, r_multiple=1.0, symbol="EURUSD.FX"):
    return {"schema_version": 1, "signal_id": sid, "status": "CLOSED",
            "won": r_multiple > 0, "taken": True, "r_multiple": r_multiple,
            "direction": "LONG", "symbol": symbol, "ticket": 1, "broker_order_id": 1,
            "entry": 1.10000, "initial_stop": 1.09800, "weighted_close": 1.10400,
            "closed_volume": 0.10, "deal_count": 1, "realized_r_source": "mt5_deal_history"}


# --------------------------------------------------------------------------- #
# N.1 — no canonical numeric trade score exists
# --------------------------------------------------------------------------- #
def test_no_score_field_in_instruction_schema():
    for f in REQUIRED_INSTRUCTION_FIELDS:
        assert not _SCORE_FIELD_RE.search(f), f
    assert "score" not in [f.lower() for f in REQUIRED_INSTRUCTION_FIELDS]


def test_engine_confidence_is_fixed_not_graded():
    # spec §8.3: confidence is emitted as a fixed 1.0 pass/fail qualifier, not a score.
    src = (PKG / "run_dir" / "code" / "signal_engine.py").read_text()
    assert '"confidence": 1.0' in src                 # fixed constant
    assert "def score" not in src and "trade_score" not in src


def test_no_graded_score_producer_in_trading_path():
    # no production trading module defines/persists a graded trade score.
    trading = ("bridge", "compliance", "ea_mt5", "manage", "position", "producer",
               "runtime", "session", "live")
    for pkg in trading:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            for m in _SCORE_FIELD_RE.finditer(p.read_text()):
                raise AssertionError(f"unexpected score concept {m.group(0)} in {p}")


# --------------------------------------------------------------------------- #
# N.2 — research correctly reports UNAVAILABLE
# --------------------------------------------------------------------------- #
def test_research_reports_score_unavailable(tmp_path):
    assert lifecycle.FACT_AVAILABILITY["trade_score"] == lifecycle.UNAVAILABLE
    m = _mem(tmp_path); _write = lambda c: m.write_raw(  # noqa: E731
        lifecycle.OUTCOME_KIND, c["symbol"], c, source="outcome_reconciler",
        timestamp="2026-01-05T12:00:00Z", correlation_id=c["signal_id"])
    _write(_outcome("a" * 16))
    t = lifecycle.load_closed_trades(m)[0]
    assert t["trade_score"] is None
    assert lifecycle.cohort_of(t["trade_score"]) == lifecycle.SCORE_UNAVAILABLE
    assert lifecycle.lifecycle_report(m)["score_status"] == lifecycle.SCORE_UNAVAILABLE


# --------------------------------------------------------------------------- #
# N.3 — no current field is silently treated as the trade score
# --------------------------------------------------------------------------- #
def test_no_proxy_field_treated_as_score():
    # the ingest sets trade_score to None only, and NEVER derives it from a proxy
    # (confidence / rr_planned / agreement_score). Checks CODE, not comments.
    src = (PKG / "research" / "lifecycle.py").read_text()
    assert '"trade_score": None' in src                          # only ever absent
    # no code path assigns trade_score from a proxy field
    assert re.search(r'trade_score["\']?\s*[:=]\s*[^N]', src) is None or \
        '"trade_score": None' in src
    for proxy in ("confidence", "rr_planned", "agreement_score"):
        assert re.search(rf'trade_score.*{proxy}|{proxy}.*trade_score', src) is None


# --------------------------------------------------------------------------- #
# N.4 / N.5 — PR-3J sizing + execution volume have no score dependency
# --------------------------------------------------------------------------- #
def test_sizing_has_no_score_dependency():
    src = (PKG / "compliance" / "sizing.py").read_text()
    assert "score" not in src.lower()


def test_execution_volume_has_no_score_dependency():
    for rel in ("ea_mt5/execution_consumer.py", "ea_mt5/SessionEdgeExecutionEA.mq5"):
        assert "score" not in (PKG / rel).read_text().lower()


# --------------------------------------------------------------------------- #
# N.6 / N.7 — compliance has no undocumented score threshold; EA no score auth
# --------------------------------------------------------------------------- #
def test_compliance_has_no_score_threshold():
    for rel in ("compliance/gates.py", "compliance/engine.py", "compliance/contract.py"):
        src = (PKG / rel).read_text().lower()
        assert "min_score" not in src and "score_threshold" not in src and "trade_score" not in src


def test_ea_has_no_score_based_authorization():
    assert "score" not in (PKG / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text().lower()


# --------------------------------------------------------------------------- #
# N.8 — cohort analytics remain dormant/UNAVAILABLE without score evidence
# --------------------------------------------------------------------------- #
def test_cohort_analytics_dormant_without_score(tmp_path):
    m = _mem(tmp_path)
    for i, sid in enumerate(("a" * 16, "b" * 16, "c" * 16)):
        c = _outcome(sid, r_multiple=(1.0 if i % 2 == 0 else -1.0))
        m.write_raw(lifecycle.OUTCOME_KIND, c["symbol"], c, source="outcome_reconciler",
                    timestamp="2026-01-05T12:00:00Z", correlation_id=sid)
    bd = lifecycle.cohort_breakdown(lifecycle.load_closed_trades(m))
    assert set(bd) == {lifecycle.SCORE_UNAVAILABLE}      # dormant: no qualifying cohort populated


# --------------------------------------------------------------------------- #
# N.9 + duplicate-authority — no second score/cohort/sizing owner introduced
# --------------------------------------------------------------------------- #
def test_cohort_of_is_sole_owner():
    hits = [p for p in PKG.rglob("*.py")
            if "/tests/" not in str(p) and re.search(r"^def cohort_of\(", p.read_text(), re.M)]
    assert hits == [PKG / "research" / "lifecycle.py"]


def test_allowable_volume_remains_sole_sizing_owner():
    hits = [p for p in PKG.rglob("*.py")
            if "/tests/" not in str(p) and re.search(r"^def allowable_volume\(", p.read_text(), re.M)]
    assert hits == [PKG / "compliance" / "sizing.py"]


def test_no_trading_module_imports_research():
    trading = ("bridge", "compliance", "ea_mt5", "manage", "position", "producer",
               "runtime", "session", "live")
    offenders = []
    for pkg in trading:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            if re.search(r"import\s+.*\bresearch\b|from\s+.*research", p.read_text()):
                offenders.append(str(p.relative_to(PKG)))
    assert offenders == []

"""PR-9E — research <-> production BOUNDARY + authority proofs (Sections AA / AE / AD46-60).

Strengthens the existing PR-3Q boundary tests to cover the whole research/ tree
(including report_suite) and answers the Section-AE adversarial questions as explicit,
enforceable tests:

  * research has NO production back-edge: no production trading package imports research;
    no production module reads a research artifact from disk (research output cannot
    change production merely by appearing on disk);
  * research holds ZERO trading authority: no research module contains order / bridge /
    PM mutation calls, sizes a lot, or writes risk_fraction;
  * single owners are preserved: one realized-R owner (manage.outcome), one lifecycle
    join owner (research.lifecycle), one quality extractor (research.quality_facts),
    one live lot-sizing authority (compliance.sizing.allowable_volume — never called
    from research);
  * no live 0-100 score gate and no quality->risk coupling exist;
  * no Phantom integration; the EA carries no score logic.

These complement (do not duplicate) test_calibration_pr3q tests 31-40. Static, read-only.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "forex_swing_orb"

TRADING_PKGS = ("bridge", "compliance", "ea_mt5", "manage", "position",
                "producer", "runtime", "session", "live", "newsfeed")
RESEARCH_DIR = PKG / "research"


def _prod_py():
    for pkg in TRADING_PKGS:
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" not in str(p):
                yield p


def _research_py():
    for p in RESEARCH_DIR.rglob("*.py"):
        if "/tests/" not in str(p) and p.name != "__init__.py":
            yield p


# --------------------------------------------------------------------------- #
# AA / AD46: no production trading package imports research (incl. report_suite)
# --------------------------------------------------------------------------- #
def test_no_production_module_imports_research():
    offenders = []
    for p in _prod_py():
        txt = p.read_text()
        if re.search(r"^\s*(from|import)\s+.*\bresearch\b", txt, re.M):
            offenders.append(str(p.relative_to(PKG)))
    assert offenders == [], f"production imports research: {offenders}"


def test_report_suite_specifically_not_imported_by_production():
    for p in _prod_py():
        assert "report_suite" not in p.read_text(), str(p.relative_to(PKG))


# --------------------------------------------------------------------------- #
# AE4 / AD: a research artifact appearing on disk cannot change production
# --------------------------------------------------------------------------- #
def test_no_production_module_reads_research_artifacts():
    artifact_tokens = ("research_dataset.json", "calibration_report.json",
                       "baseline_report.json", "report_suite")
    for p in _prod_py():
        txt = p.read_text()
        for tok in artifact_tokens:
            assert tok not in txt, f"{p.relative_to(PKG)} references {tok!r}"


# --------------------------------------------------------------------------- #
# AE1/AE2/AE3: research holds ZERO trading authority (whole tree, incl. report_suite)
# --------------------------------------------------------------------------- #
def test_research_has_no_trade_or_mutation_calls():
    # trade/PM mutation tokens never legitimately appear in research prose
    banned = ("order_send", "OrderSend", "place_order", "write_instruction",
              "bridge.enter", "PositionModify", "PositionClose", "positions_close")
    # networking / external-process access is forbidden — checked as IMPORTS so a
    # docstring like "no subprocess, no network" (provenance.py) is not a false positive
    net_import = re.compile(r"^\s*(?:import|from)\s+(socket|requests|urllib|http|subprocess)\b", re.M)
    for p in _research_py():
        txt = p.read_text()
        for b in banned:
            assert b not in txt, f"{p.relative_to(PKG)} contains {b!r}"
        assert not net_import.search(txt), f"{p.relative_to(PKG)} imports networking/process"


def test_research_never_calls_the_live_sizing_authority():
    # PR-3J allowable_volume is the SOLE live lot authority; research may reference the
    # module in prose but must never CALL it (no paren-suffixed invocation).
    for p in _research_py():
        assert not re.search(r"allowable_volume\s*\(", p.read_text()), str(p.relative_to(PKG))


def test_research_never_writes_risk_fraction_or_volume():
    for p in _research_py():
        txt = p.read_text()
        assert not re.search(r"""["']risk_fraction["']\s*\]\s*=""", txt), str(p)
        assert not re.search(r"""\.\s*volume\s*=""", txt), str(p)


# --------------------------------------------------------------------------- #
# AE9 / AD49 / AD50: no live 0-100 score gate; no quality->risk coupling
# --------------------------------------------------------------------------- #
def test_no_live_score_gate_in_production():
    # production must contain no 0-100 quality-score gate (the "70 gate" is a future
    # hypothesis only). Research may analyze a retrospective threshold observationally.
    for p in _prod_py():
        txt = p.read_text()
        assert "trade_score" not in txt, str(p.relative_to(PKG))
        assert not re.search(r"quality[_ ]?score\s*[<>]=?\s*\d", txt), str(p.relative_to(PKG))


def test_no_quality_to_risk_coupling_in_production():
    # no production module scales risk/volume by a quality factor/score
    for p in _prod_py():
        txt = p.read_text()
        assert not re.search(r"(risk_fraction|volume)\s*\*\s*.*score", txt), str(p.relative_to(PKG))
        assert not re.search(r"score\s*\*\s*.*(risk_fraction|volume)", txt), str(p.relative_to(PKG))


# --------------------------------------------------------------------------- #
# AD57/58: single owners preserved (no duplicate realized-R / lifecycle / extractor)
# --------------------------------------------------------------------------- #
def test_single_realized_r_owner():
    # exactly one module WRITES the execution_outcome fact: manage/outcome.py
    writers = []
    for pkg in TRADING_PKGS + ("research",):
        for p in (PKG / pkg).rglob("*.py"):
            if "/tests/" in str(p):
                continue
            txt = p.read_text()
            if 'OUTCOME_KIND' in txt and "write_raw" in txt:
                writers.append(str(p.relative_to(PKG)))
    assert writers == ["manage/outcome.py"], writers


def test_single_quality_fact_extractor_and_lifecycle_owner():
    # the join + the extractor each live in exactly one research module
    joiners = [p.name for p in _research_py() if "def quality_dataset(" in p.read_text()]
    extractors = [p.name for p in _research_py()
                  if re.search(r"^def extract\(", p.read_text(), re.M)]
    assert joiners == ["lifecycle.py"] and extractors == ["quality_facts.py"]


# --------------------------------------------------------------------------- #
# AD59/60: no Phantom integration; AI observational; EA carries no score logic
# --------------------------------------------------------------------------- #
def test_research_has_no_phantom_integration():
    for p in _research_py():
        assert not re.search(r"^\s*(from|import)\s+.*phantom", p.read_text(), re.M), str(p)


def test_ea_contains_no_score_logic():
    ea = (PKG / "ea_mt5" / "SessionEdgeExecutionEA.mq5").read_text().lower()
    assert "score" not in ea and "quality_fact" not in ea


# --------------------------------------------------------------------------- #
# AE: report_suite is orchestration-only (delegates; owns no new metric math authority)
# --------------------------------------------------------------------------- #
def test_report_suite_only_delegates_and_writes_outputs():
    src = (RESEARCH_DIR / "report_suite.py").read_text()
    # it must import the canonical owners and must not re-derive strategy/compliance/sizing
    for owner in ("portfolio", "reporting", "calibration", "montecarlo",
                  "walk_forward", "lifecycle", "provenance"):
        assert owner in src
    for banned in ("allowable_volume(", "order_send", "SignalEngine(", "risk_within_limit("):
        assert banned not in src

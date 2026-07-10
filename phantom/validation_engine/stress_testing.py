"""Stress Testing (ADR-030 §5.7): replays scenarios tagged with extreme
market conditions (high spread, low liquidity, gap opens, flash crashes,
COVID, Brexit, central bank intervention, NFP, FOMC, holiday trading,
weekend gaps) through the same verification path as Historical Replay,
confirming it never raises and that a defined subset of conditions
show a correctly-restricted recorded Compliance decision."""

from __future__ import annotations

from typing import Tuple

from .models import HistoricalScenario, StressScenarioTag, StressTestResult
from .replay import verify_scenario

# Conditions under which a correctly-behaving Compliance Engine must
# never have recorded `ready_for_bridge=True` -- outright market
# closures/dislocations, not merely elevated caution (high spread/low
# liquidity/NFP/FOMC/COVID/Brexit reduce size or add caution but do not
# universally require a hard block, so they are not held to this bar).
_HARD_RESTRICTION_TAGS = frozenset({
    StressScenarioTag.HOLIDAY_TRADING,
    StressScenarioTag.WEEKEND_GAP,
    StressScenarioTag.FLASH_CRASH,
    StressScenarioTag.CENTRAL_BANK_INTERVENTION,
})


def run_stress_test(scenario: HistoricalScenario) -> StressTestResult:
    tag = scenario.stress_tag
    if tag is None:
        raise ValueError("run_stress_test requires a scenario with a stress_tag set")

    try:
        verification = verify_scenario(scenario)
        survived = True
        error = None
    except Exception as exc:  # noqa: BLE001 -- stress testing must observe, never propagate
        verification = None
        survived = False
        error = repr(exc)

    if not survived:
        return StressTestResult(
            scenario_id=scenario.scenario_id, tag=tag, survived=False, error=error,
            correctly_restricted=False, detail="replay verification raised an exception under stress",
        )

    if tag in _HARD_RESTRICTION_TAGS:
        correctly_restricted = not scenario.compliance.ready_for_bridge
        detail = (
            "compliance correctly withheld ready_for_bridge under a hard-restriction stress condition"
            if correctly_restricted
            else "compliance recorded ready_for_bridge=True under a hard-restriction stress condition -- investigate"
        )
    else:
        correctly_restricted = True
        detail = f"{tag.value} does not require a hard block -- verified only that replay survived"

    return StressTestResult(
        scenario_id=scenario.scenario_id, tag=tag, survived=True, error=None,
        correctly_restricted=correctly_restricted, detail=detail,
    )


def run_stress_tests(scenarios) -> Tuple[StressTestResult, ...]:
    return tuple(run_stress_test(s) for s in scenarios if s.stress_tag is not None)


__all__ = ["run_stress_test", "run_stress_tests"]

"""Bull vs Bear Debate Agent (`ADR-021` §3, item 2).

**Research only — never a trading signal** (`ADR-021` Hard Rule 6):
`DebateThesis` has no `direction`/`lot_size`/`entry_price`/`stop_loss`/
`take_profit` field, and this module has no method any pipeline stage
could call for a trading decision. The confidence score is a transparent
ratio (agreeing signals / considered signals) over already-recorded
`ScannerObservation` fields — never a fabricated black-box number.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple

from ..scanner.models import Direction, MarketPhase, ScannerObservation
from .models import DebateStance, DebateThesis, SCHEMA_VERSION, ThesisCase

_BULLISH_PHASES = (MarketPhase.MARKUP, MarketPhase.ACCUMULATION)
_BEARISH_PHASES = (MarketPhase.MARKDOWN, MarketPhase.DISTRIBUTION)


def _phase_direction(phase: MarketPhase) -> Direction:
    if phase in _BULLISH_PHASES:
        return Direction.UP
    if phase in _BEARISH_PHASES:
        return Direction.DOWN
    return Direction.UNKNOWN


def _collect_directional_signals(observation: ScannerObservation) -> Tuple[Tuple[str, Direction], ...]:
    signals = [
        ("external structure", observation.external_structure.direction),
        ("internal structure", observation.internal_structure.direction),
        ("market phase", _phase_direction(observation.phase)),
    ]
    for timeframe, reading in observation.trend.items():
        signals.append((f"{timeframe} trend", reading.direction))
    return tuple(signals)


class BullBearDebateAgent:
    def generate_thesis(self, report_id: str, symbol: str, observation: ScannerObservation, now: datetime) -> DebateThesis:
        signals = _collect_directional_signals(observation)
        considered = [(name, direction) for name, direction in signals if direction != Direction.UNKNOWN]

        up_signals = [name for name, direction in considered if direction == Direction.UP]
        down_signals = [name for name, direction in considered if direction == Direction.DOWN]
        neutral_signals = [name for name, direction in considered if direction == Direction.NEUTRAL]

        total = len(considered)
        bullish_case = ThesisCase(
            stance=DebateStance.BULLISH,
            summary=(
                f"{len(up_signals)} of {total} considered signal(s) point up." if total else "No directional signals available."
            ),
            supporting_evidence=tuple(up_signals),
        )
        bearish_case = ThesisCase(
            stance=DebateStance.BEARISH,
            summary=(
                f"{len(down_signals)} of {total} considered signal(s) point down." if total else "No directional signals available."
            ),
            supporting_evidence=tuple(down_signals),
        )
        neutral_case = ThesisCase(
            stance=DebateStance.NEUTRAL,
            summary=(
                f"{len(neutral_signals)} of {total} considered signal(s) are neutral/mixed." if total
                else "Insufficient data to form a directional view."
            ),
            supporting_evidence=tuple(neutral_signals),
        )

        if total == 0:
            confidence = 0.0
            winning_stance = DebateStance.NEUTRAL
        else:
            counts = {
                DebateStance.BULLISH: len(up_signals),
                DebateStance.BEARISH: len(down_signals),
                DebateStance.NEUTRAL: len(neutral_signals),
            }
            winning_stance = max(counts, key=lambda stance: counts[stance])
            top_count = counts[winning_stance]
            if list(counts.values()).count(top_count) > 1:
                winning_stance = DebateStance.NEUTRAL
            confidence = top_count / total

        final_summary = (
            f"{symbol}: leaning {winning_stance.value.lower()} "
            f"(confidence {confidence:.2f} from {total} considered signal(s)). Research only — not a trading signal."
        )

        return DebateThesis(
            schema_version=SCHEMA_VERSION,
            report_id=report_id,
            symbol=symbol,
            generated_at=now,
            bullish_case=bullish_case,
            bearish_case=bearish_case,
            neutral_case=neutral_case,
            confidence_score=confidence,
            final_summary=final_summary,
        )


__all__ = ["BullBearDebateAgent"]

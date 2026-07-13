"""Thread-safe pending-exposure reservation ledger (ADR-027 Hard Rule 5).

Prevents two concurrent `evaluate()` calls from both being approved in
a way that, together, breaches a configured exposure/heat/correlation
limit. `RiskEngine` holds exactly one `ReservationLedger` instance for
its lifetime; every reservation/read/release goes through its single
lock, so "check current exposure, then add a new reservation" is one
atomic step, never two racing ones.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    pair: str
    risk_r: float
    created_at: datetime


class ReservationLedger:
    """In-memory only -- reservations do not survive process restart by
    design; a restarted engine starts with zero pending reservations,
    which is the safe (under-count, never over-count) direction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reservations: Dict[str, Reservation] = {}
        self._id_counter = itertools.count(1)

    def pending_total_r(self) -> float:
        with self._lock:
            return sum(r.risk_r for r in self._reservations.values())

    def pending_for_pair_r(self, pair: str) -> float:
        with self._lock:
            return sum(r.risk_r for r in self._reservations.values() if r.pair == pair)

    def reserve(self, pair: str, risk_r: float) -> str:
        """Unconditional reservation -- prefer `reserve_if` when the
        reservation depends on a check over current pending state."""


        with self._lock:
            reservation_id = f"RSV-{next(self._id_counter)}"
            self._reservations[reservation_id] = Reservation(
                reservation_id=reservation_id, pair=pair, risk_r=risk_r,
                created_at=datetime.now(timezone.utc),
            )
            return reservation_id

    def reserve_if(
        self, pair: str, risk_r: float, predicate: Callable[[Tuple[Reservation, ...]], bool],
    ) -> Optional[str]:
        """Atomically evaluates `predicate(pending_reservations)` and, if
        it returns `True`, reserves `risk_r` for `pair` before the lock is
        released -- the check and the reservation happen as one
        indivisible step, so no concurrent call can slip a reservation in
        between (ADR-027 Hard Rule 5)."""

        with self._lock:
            pending = tuple(self._reservations.values())
            if not predicate(pending):
                return None
            reservation_id = f"RSV-{next(self._id_counter)}"
            self._reservations[reservation_id] = Reservation(
                reservation_id=reservation_id, pair=pair, risk_r=risk_r,
                created_at=datetime.now(timezone.utc),
            )
            return reservation_id

    def release(self, reservation_id: str) -> bool:
        with self._lock:
            return self._reservations.pop(reservation_id, None) is not None

    def snapshot(self) -> Tuple[Reservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._reservations)


__all__ = ["Reservation", "ReservationLedger"]

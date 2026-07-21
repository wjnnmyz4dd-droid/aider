"""Pair-level in-flight command registry (Runtime-owned).

`RuntimeOrchestrator` generates a fresh `TradeCommand`/`correlation_id`
every cycle (`bridge_handoff.build_trade_command()`) whenever
`compliance.ready_for_bridge` is true, with no memory of a command it
already submitted for the same pair last cycle. This registry closes
that gap: it tracks at most one outstanding (submitted, not yet
resolved) command per pair, so `RuntimeOrchestrator` can refuse to
generate a second one until the first reaches a terminal state (an
`ExecutionReport` was recorded against it, checked via
`BridgeEngine.command_resolved()`) or expires (`ttl_seconds`, a bound
against a command whose `ExecutionReport` never arrives).

Deliberately Runtime-owned, not Bridge-owned: `titan_protocol/bridge/`
is the execution relay only, never a decision authority (ADR-023) --
"should a second command be allowed while the first is unresolved" is a
decision-time gate, and belongs alongside Runtime's other gates
(risk/compliance), not inside the relay itself. This module has no
dependency on `titan_protocol.bridge` at all; it is handed a plain
`is_resolved(correlation_id) -> bool` callable by its caller (see
`reconcile()`), matching the same narrow-callable pattern
`RuntimeOrchestrator.bridge_submit` already uses.

Undelivered-command abandonment (fix for "the runtime never exits the
failure loop"): `CommandQueue.poll()` silently drops a pending command
once it is older than `BridgeConfig.command_ttl_seconds` -- the EA
simply never receives it, with no signal back to Runtime that this
happened. Before this fix, `has_unresolved()` had no way to tell "the EA
is still working on this" apart from "this command was never delivered
at all and is already gone from the queue" -- both looked identical (an
entry present in `_by_pair`, not yet resolved), so a pair stayed blocked
for the full `ttl_seconds` (this registry's own, much longer bound, meant
for "delivered but the result never arrived") even though the underlying
command had already vanished from `CommandQueue` after `command_ttl_seconds`.
Under a persistently flaky poll transport this reproduces indefinitely:
submit, silently expire undelivered, wait out most of `ttl_seconds` doing
nothing, resubmit, repeat -- Compliance keeps approving entries that never
reach the market. `reconcile()` now accepts an optional `is_abandoned`
callable (`BridgeEngine.command_abandoned`) and, when supplied, drops an
entry immediately once it reports abandonment -- freeing the pair for a
fresh submission far sooner than the full `ttl_seconds`, instead of
blindly waiting it out. Defaults to `None`/disabled, so any existing
caller that does not opt in keeps exactly its prior behavior.

Deliberately a single atomic callable, not "is it delivered" plus a
separately-computed age here: an earlier version of this fix combined an
`is_delivered` callable with this registry's own `undelivered_grace_seconds`
threshold, composed from two independent reads (this registry's own
`now`/`entry.submitted_at`, and `CommandQueue`'s own `_delivered_ids`) --
taken at two different instants, under two different locks
(`InFlightCommandRegistry._lock` and `CommandQueue._lock`), with no
atomicity between them. That left two real defects: (1) a genuinely
delivered command could, under retention settings shorter than this
registry's own windows, appear "not delivered" again once `CommandQueue`
purged it, causing a live reservation to be released while the EA might
still execute it; (2) a `poll()` call landing at nearly the same instant
as this registry's own age check was a genuine, unguarded race -- the
two locks provide no ordering guarantee relative to each other, so this
registry's read could observe "not yet delivered" a moment before (or
after) `poll()` committed the opposite fact, risking both a released
reservation and a live delivery for the same correlation_id at once
(a duplicate-command/duplicate-position risk). `is_abandoned` closes
both: `CommandQueue.is_abandoned()` is evaluated entirely under
`CommandQueue`'s own single lock, using its own `command_ttl_seconds`
and its own `_delivered_ids`/`_commands` state at one consistent
instant -- the only object that actually owns both facts. A delivered
command is never abandoned, and a concurrent `poll()` (holding the same
lock) can never interleave with this check.

Post-resolution position confirmation: an `ExecutionReport` can arrive
(marking a command resolved) before the *next* `/bridge/positions`
snapshot has caught up to reflect the position it just opened -- these
are two independently-timed EA-reported events, not one atomic update.
Dropping a pair's in-flight entry the instant its command resolves would
therefore leave a real window where `PortfolioState` still shows the old
(pre-execution) position count, and a second command for the same pair
could slip through before the position is actually visible. This
registry closes that window itself: `reconcile()` moves a resolved pair
into a second, "awaiting position confirmation" state instead of
clearing it outright, and only `confirm_position_report()` -- given the
timestamp of the Bridge's most recent positions snapshot -- can release
it, once that snapshot is provably no older than the resolution itself.
This never infers position truth from the `ExecutionReport` (that
remains solely `BridgeEngine.latest_positions`'s job); it only delays
when a resolved pair is allowed to accept a new submission. TTL-expired
entries (no `ExecutionReport` ever arrived) skip this extra wait -- by
the time TTL has elapsed there is no fresher signal to wait for, and
piling more delay onto an already-lost report would just compound it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class _InFlightEntry:
    correlation_id: str
    submitted_at: datetime


class InFlightCommandRegistry:
    """Thread safety: reached from the live-cycle loop only in this
    codebase's current wiring (one thread), but guarded by a lock
    regardless -- cheap, and removes any future assumption that this
    can only ever be called single-threaded."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._by_pair: Dict[str, _InFlightEntry] = {}
        # Pair -> the moment reconcile() observed that pair's command
        # resolve via a real ExecutionReport (never set on TTL expiry --
        # see reconcile()). has_unresolved() keeps blocking a pair listed
        # here until confirm_position_report() releases it.
        self._awaiting_position_confirmation: Dict[str, datetime] = {}

    def has_unresolved(self, pair: str, now: datetime) -> bool:
        """True if `pair` has a command outstanding that has neither
        resolved nor expired, OR has resolved but is still awaiting a
        post-resolution positions snapshot (see class docstring). Never
        mutates state -- expiry is only ever applied by `reconcile()`, so
        a caller that checks this without ever calling `reconcile()`
        still gets a correct answer for the TTL case (evaluated fresh
        here too), but entries are only cleaned up by `reconcile()`/
        `confirm_position_report()`."""
        with self._lock:
            entry = self._by_pair.get(pair)
            if entry is not None and (now - entry.submitted_at).total_seconds() <= self._ttl_seconds:
                return True
            return pair in self._awaiting_position_confirmation

    def record_submission(self, pair: str, correlation_id: str, now: datetime) -> None:
        with self._lock:
            self._by_pair[pair] = _InFlightEntry(correlation_id=correlation_id, submitted_at=now)
            self._awaiting_position_confirmation.pop(pair, None)

    def reconcile(
        self,
        now: datetime,
        is_resolved: Callable[[str], bool],
        is_abandoned: Optional[Callable[[str], bool]] = None,
    ) -> int:
        """Drops every tracked entry that has either resolved (per
        `is_resolved(correlation_id)`, a caller-supplied query -- this
        module never assumes how resolution is determined), been
        abandoned (per `is_abandoned`, a single atomic query -- see this
        module's own docstring for why the abandonment decision must be
        one atomic callable, not composed here from separate delivery/age
        reads -- only checked when `is_abandoned` is supplied), or
        expired past `ttl_seconds`. A resolved (not expired, not
        abandoned) pair moves into `_awaiting_position_confirmation`
        rather than being fully cleared -- `has_unresolved()` keeps
        blocking it until `confirm_position_report()` releases it. An
        abandoned or plain-expired entry is dropped outright: nothing
        executed, so there is no position report to await. Returns the
        number of entries dropped this call, for logging. Call once per
        live cycle, before checking `has_unresolved()` for that cycle's
        pairs."""
        with self._lock:
            to_drop = []
            for pair, entry in self._by_pair.items():
                if is_resolved(entry.correlation_id):
                    to_drop.append(pair)
                    self._awaiting_position_confirmation[pair] = now
                    continue
                if is_abandoned is not None and is_abandoned(entry.correlation_id):
                    to_drop.append(pair)
                    continue
                if (now - entry.submitted_at).total_seconds() > self._ttl_seconds:
                    to_drop.append(pair)
            for pair in to_drop:
                del self._by_pair[pair]
            return len(to_drop)

    def confirm_position_report(self, positions_snapshot_at: Optional[datetime]) -> int:
        """Call once per live cycle with `BridgeEngine.
        last_positions_received_at`. Releases every pair in
        `_awaiting_position_confirmation` whose resolution happened at or
        before that snapshot -- proof `PortfolioState` this cycle
        reflects the post-execution reality, not a stale pre-execution
        one. A `None` snapshot (Bridge has never received a positions
        report at all) confirms nothing -- fail-closed. Returns the
        number of pairs newly released, for logging."""
        if positions_snapshot_at is None:
            return 0
        with self._lock:
            confirmed = [
                pair for pair, resolved_at in self._awaiting_position_confirmation.items()
                if resolved_at <= positions_snapshot_at
            ]
            for pair in confirmed:
                del self._awaiting_position_confirmation[pair]
            return len(confirmed)

    def correlation_id_for(self, pair: str) -> Optional[str]:
        with self._lock:
            entry = self._by_pair.get(pair)
            return entry.correlation_id if entry is not None else None

    def in_flight_count(self) -> int:
        with self._lock:
            return len(self._by_pair)

    def awaiting_position_confirmation_count(self) -> int:
        with self._lock:
            return len(self._awaiting_position_confirmation)

    def is_awaiting_position_confirmation(self, pair: str) -> bool:
        with self._lock:
            return pair in self._awaiting_position_confirmation


__all__ = ["InFlightCommandRegistry"]

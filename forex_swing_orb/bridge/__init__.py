"""Session Edge Filesystem Execution Bridge (Phase 2 — transport only).

Deterministic, filesystem-only transport of trade instructions from the Session
Edge strategy engine (producer) to a future execution layer (consumer). It never
executes trades, never talks to MT5/brokers, and uses no networking.

Public API:
    open_bridge(root, cfg, hook) -> (paths, ledger, audit, consumer)
    producer.write_instruction / write_instructions
    Consumer.claim / claim_next / process
    reconcile.recover
"""

from __future__ import annotations

from . import serialize  # noqa: F401
from .config import BridgeConfig, DEFAULT_CONFIG
from .paths import BridgePaths
from .ledger import DedupLedger
from .audit import AuditLog
from .contract import (ResultState, ReasonCode, HookPosture, build_result,
                       build_ack, terminal_family)
from .dedup import SeenResolver
from .producer import write_instruction, write_instructions, ProducerError
from .consumer import Consumer, validation_only_hook
from .reconcile import recover

__all__ = [
    "BridgeConfig", "DEFAULT_CONFIG", "BridgePaths", "DedupLedger", "AuditLog",
    "ResultState", "ReasonCode", "HookPosture", "SeenResolver",
    "build_result", "build_ack", "terminal_family",
    "write_instruction", "write_instructions", "ProducerError", "Consumer",
    "validation_only_hook", "recover", "open_bridge", "serialize",
]


def open_bridge(root, cfg=DEFAULT_CONFIG, hook=None,
                hook_posture=HookPosture.VALIDATION_ONLY):
    """Create/ensure a bridge tree at ``root`` and return its wired components."""
    paths = BridgePaths(root).ensure()
    ledger = DedupLedger(paths.dedup_ledger)
    audit = AuditLog(paths.audit_log)
    resolver = SeenResolver(paths, ledger, cfg)
    consumer = Consumer(paths, cfg, ledger, audit, hook=hook,
                        hook_posture=hook_posture, resolver=resolver)
    return paths, ledger, audit, consumer

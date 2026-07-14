"""Broker symbol normalization -- Bridge's own transport/normalization
concern (ADR-023), never a per-engine one. Real brokers often report
symbols with a house suffix/prefix (e.g. `EURUSD.a`, `m.EURUSD`)
instead of Titan Protocol's canonical 6-letter pair name (`EURUSD`).
Every symbol the EA reports is normalized to canonical form exactly
once, at the Bridge's own ingress boundary, before it reaches
`MarketDataIngestionEngine` or any other engine -- so `enabled_pairs`/
`allowed_pairs` membership checks, `pair_currencies()` 3+3 slicing, and
every downstream comparison keep working against one consistent name,
regardless of which broker is connected.

`explicit_map` takes priority over the suffix/prefix rule -- for the
rare broker whose naming doesn't fit a single fixed affix (e.g. one
pair renamed entirely)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class SymbolMapping:
    broker_suffix: str = ""
    broker_prefix: str = ""
    #: canonical -> broker, only for exceptions the suffix/prefix rule
    #: doesn't cover. Frozen dataclasses can't default-mutate a dict, so
    #: this is stored as a sorted tuple of pairs and exposed as a dict.
    explicit_map: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "explicit_map", dict(self.explicit_map))

    def to_canonical(self, broker_symbol: str) -> str:
        for canonical, broker in self.explicit_map.items():
            if broker == broker_symbol:
                return canonical
        symbol = broker_symbol
        if self.broker_prefix and symbol.startswith(self.broker_prefix):
            symbol = symbol[len(self.broker_prefix):]
        if self.broker_suffix and symbol.endswith(self.broker_suffix):
            symbol = symbol[: -len(self.broker_suffix)]
        return symbol

    def to_broker(self, canonical_symbol: str) -> str:
        if canonical_symbol in self.explicit_map:
            return self.explicit_map[canonical_symbol]
        return f"{self.broker_prefix}{canonical_symbol}{self.broker_suffix}"


__all__ = ["SymbolMapping"]

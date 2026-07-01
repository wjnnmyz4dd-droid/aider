"""Application wiring: a single object that owns the shared pipeline state.

Holding the ORB engine, scanner and log sink together means the API can report
exactly what the scanner has seen, with no duplicate state.
"""

from __future__ import annotations

from typing import Optional

from .config import Config, DEFAULT_CONFIG
from .logging_sink import LogSink
from .orb import ORBEngine
from .scanner import Scanner


class PhantomApp:
    def __init__(self, config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None):
        self.config = config
        self.sink = LogSink(path=log_path)
        self.orb = ORBEngine(config)
        self.scanner = Scanner(config, sink=self.sink, orb_engine=self.orb)

    def scan(self, snapshots):
        return self.scanner.scan(snapshots)

    def scan_symbol(self, snap):
        return self.scanner.scan_symbol(snap)


def create_app(config: Config = DEFAULT_CONFIG, log_path: Optional[str] = None) -> PhantomApp:
    return PhantomApp(config=config, log_path=log_path)

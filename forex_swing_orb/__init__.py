"""Session Edge — Forex Swing-ORB project package.

Subpackages:
    bridge   -- Filesystem Execution Bridge (Phase 2, transport only)
    ea_mt5   -- MT5 Execution Adapter (Phase 3): reference impl + MQL5 EA source

The strategy engine deliverable lives under ``run_dir/code/signal_engine.py`` and
is loaded by file path (the way Vibe-Trading loads a run-dir engine), not imported
as part of this package.
"""

"""Phantom — modular FX scanning & scoring engine.

The package is organised as a pipeline:

    market data ─► regime ─► structure ─► guards ─► ORB ─► scorer ─► scanner ─► api

Nothing in here places orders. The scanner produces a *decision*
(APPROVE / WATCHLIST / BLOCK); execution lives outside this package.
"""

__version__ = "0.1.0"

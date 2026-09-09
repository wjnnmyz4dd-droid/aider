"""Monte Carlo simulation (Phase 9B) — deterministic, EXPLICITLY seeded.

Bootstrap-resamples an existing sequence of realized R-multiples to estimate the
distribution of terminal equity and max drawdown. Randomness ONLY via an explicit
integer seed (``random.Random(seed)``) — identical (r_multiples, sims, seed) ->
identical output. No wall clock, no UUID, no networking. It generates no orders and
consumes only already-realized results.
"""

from __future__ import annotations

import math
import random

from . import portfolio


class MonteCarloError(ValueError):
    pass


def _percentile(sorted_xs, p):
    if not sorted_xs:
        return 0.0
    k = (len(sorted_xs) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_xs[int(k)]
    return sorted_xs[lo] * (hi - k) + sorted_xs[hi] * (k - lo)


def bootstrap(r_multiples, *, sims, seed, length=None):
    """Run ``sims`` bootstrap resamples (with replacement) of ``r_multiples``. A
    seed is REQUIRED (no unseeded randomness). Returns a deterministic distribution
    of terminal equity and max drawdown."""
    xs = [float(x) for x in r_multiples
          if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)]
    if not xs:
        raise MonteCarloError("no finite r_multiples to simulate")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise MonteCarloError("an explicit integer seed is required")
    if sims <= 0:
        raise MonteCarloError("sims must be > 0")
    n = length or len(xs)
    rng = random.Random(seed)
    terminals, drawdowns = [], []
    for _ in range(sims):
        path = [xs[rng.randrange(len(xs))] for _ in range(n)]
        eq = portfolio.equity_curve([{"r_multiple": r} for r in path])
        terminals.append(eq[-1] if eq else 0.0)
        drawdowns.append(portfolio.max_drawdown(eq))
    terminals.sort()
    drawdowns.sort()
    return {
        "sims": sims, "seed": seed, "path_length": n, "sample_size": len(xs),
        "terminal": {
            "mean": round(sum(terminals) / sims, 6),
            "p05": round(_percentile(terminals, 0.05), 6),
            "p50": round(_percentile(terminals, 0.50), 6),
            "p95": round(_percentile(terminals, 0.95), 6),
            "min": terminals[0], "max": terminals[-1],
        },
        "max_drawdown": {
            "mean": round(sum(drawdowns) / sims, 6),
            "p50": round(_percentile(drawdowns, 0.50), 6),
            "p95": round(_percentile(drawdowns, 0.95), 6),
            "worst": drawdowns[-1],
        },
    }

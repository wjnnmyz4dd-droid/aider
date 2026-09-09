"""Session Edge strategy-level 15/15 news buffer + M-3 fail-closed guard.

Documents and pins the chosen conservative Session Edge STRATEGY behavior — 15 min
before and 15 min after relevant high-impact news — as the default NewsLockoutConfig,
and that news verification is required by default (M-3: unverified never passes). This
is a Session Edge strategy guard, NOT a falsely-labeled FTMO-mandated rule. This task
did not change news logic; this test ensures it stays intact.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from forex_swing_orb.compliance.contract import NewsLockoutConfig  # noqa: E402


def test_default_news_buffer_is_15_before_and_15_after():
    cfg = NewsLockoutConfig()
    assert cfg.pre_lockout_min == 15         # 15 minutes BEFORE relevant high-impact news
    assert cfg.post_lockout_min == 15        # 15 minutes AFTER


def test_default_requires_verified_news_m3():
    # M-3: verification required by default -> an unverified bundle can never pass.
    assert NewsLockoutConfig().require_verified is True

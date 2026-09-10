"""Spontaneous-knock hook core (mission system).

Pure decision logic for gateway-idle knocks. No I/O, no sends.
See docs/mission-plan.md Phase 3.
"""

from __future__ import annotations

import random
import time
from typing import Optional


def idle_seconds(last_activity_ts: Optional[float], now: Optional[float] = None) -> float:
    if not last_activity_ts:
        return 0.0
    return max(0.0, (now if now is not None else time.time()) - last_activity_ts)


def should_spontaneous_knock(
    *,
    idle_secs: float,
    min_idle_secs: float = 1800.0,
    max_idle_secs: float = 14400.0,
    skip_probability: float = 0.5,
    rng: Optional[random.Random] = None,
) -> bool:
    if idle_secs < min_idle_secs or idle_secs > max_idle_secs:
        return False
    r = rng or random
    return r.random() >= skip_probability

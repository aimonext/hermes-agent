"""Mission monitor (mission system Phase 3): decide when a mission needs a knock.

A knock is a spontaneous status check sent when a board's mission is
``active`` but stagnant. This module only *decides*; delivery rides the
existing cron prompt path, so no new send machinery is invented here.
Jitter keeps knocks off rigid boundaries (seedable for tests).
"""

from __future__ import annotations

import random
import time
from typing import Optional

STAGNANT_AFTER = 6 * 3600
BASE_KNOCK_INTERVAL = 3 * 3600


def jittered_interval(base: int, rng: random.Random) -> float:
    """Quiet interval with +/-25% jitter so knocks feel spontaneous."""
    return base * rng.uniform(0.75, 1.25)


def knock_text(goal: str) -> str:
    """Short status-check nudge naming the mission goal."""
    goal = (goal or "").strip()
    if goal:
        return "knock knock - " + goal + " er ki khobor, kothay porjonto hoilo?"
    return "knock knock - ki korchen ekhon?"


def check_board(board=None, now=None, last_knock=None, rng=None, base_interval=BASE_KNOCK_INTERVAL):
    """Return a knock payload dict, or None when no knock is due."""
    from hermes_cli import kanban_db as kb

    rng = rng or random.Random()
    now = time.time() if now is None else now
    meta = kb.read_board_metadata(board)
    if meta.get("mission_status") != "active" or not (meta.get("mission_goal") or "").strip():
        return None
    if last_knock is None:
        last_knock = meta.get("mission_updated_at") or 0
    if now - last_knock < jittered_interval(base_interval, rng):
        return None
    return {
        "board": meta.get("slug"),
        "goal": meta.get("mission_goal"),
        "status": meta.get("mission_status"),
        "text": knock_text(meta.get("mission_goal", "")),
    }

"""Tests for cron.mission_monitor — knock decisions for stagnant missions."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest

from cron.mission_monitor import BASE_KNOCK_INTERVAL, check_board, jittered_interval, knock_text
from hermes_cli import kanban_db as kb


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_no_mission_no_knock(kanban_home):
    assert check_board("default", now=1_000_000.0, rng=random.Random(0)) is None


def test_active_stagnant_knocks(kanban_home):
    kb.set_board_mission("default", goal="Clean home", status="active")
    payload = check_board(
        "default", now=1_000_000.0, last_knock=1.0, rng=random.Random(0)
    )
    assert payload is not None
    assert payload["board"] == "default"
    assert "Clean home" in payload["text"]


def test_recent_knock_stays_quiet(kanban_home):
    kb.set_board_mission("default", goal="Clean home", status="active")
    now = time.time()
    assert (
        check_board("default", now=now, last_knock=now - 60, rng=random.Random(0))
        is None
    )


def test_complete_mission_never_knocks(kanban_home):
    kb.set_board_mission("default", goal="Clean home", status="complete")
    assert (
        check_board("default", now=1_000_000.0, last_knock=1.0, rng=random.Random(0))
        is None
    )


def test_jitter_stays_in_band():
    rng = random.Random(7)
    for _ in range(50):
        assert BASE_KNOCK_INTERVAL * 0.75 <= jittered_interval(
            BASE_KNOCK_INTERVAL, rng
        ) <= BASE_KNOCK_INTERVAL * 1.25


def test_knock_text_fallback():
    assert "ki korchen" in knock_text("")

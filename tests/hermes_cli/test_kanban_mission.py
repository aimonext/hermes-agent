"""Tests for the mission layer: board mission metadata + deterministic fan-out."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_graph import fanout_mission_task
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_set_board_mission_persists(kanban_home):
    meta = kb.set_board_mission(None, goal="Run the home clean", status="active")
    assert meta["mission_goal"] == "Run the home clean"
    assert meta["mission_status"] == "active"
    assert meta["mission_updated_at"] > 0
    again = kb.read_board_metadata(None)
    assert again["mission_goal"] == "Run the home clean"
    assert again["mission_status"] == "active"


def test_set_board_mission_rejects_bad_status(kanban_home):
    with pytest.raises(ValueError):
        kb.set_board_mission(None, status="flying")


def test_clearing_goal_resets_status(kanban_home):
    kb.set_board_mission(None, goal="Do things", status="active")
    meta = kb.set_board_mission(None, goal="")
    assert meta["mission_goal"] == ""
    assert meta["mission_status"] == "none"


def _create_root(conn, title="mission root"):
    return kb.create_task(conn, title=title, body="root", assignee="orchestrator")


def test_fanout_creates_linked_children(kanban_home):
    with kbc.connect() as conn:
        root = _create_root(conn)
    kids = [
        {"title": "find dirty clothes", "body": "search every room"},
        {"title": "sort wash vs donate", "body": "keep tomorrow's aside", "parents": [0]},
    ]
    with kbc.connect() as conn:
        ids = fanout_mission_task(conn, root, children=kids, author="mission")
    assert ids is not None and len(ids) == 2
    with kbc.connect() as conn:
        root_task = kb.get_task(conn, root)
        assert root_task.status in ("todo", "ready")
        assert set(kb.parent_ids(conn, root)) == set(ids)
        first, second = kb.get_task(conn, ids[0]), kb.get_task(conn, ids[1])
        assert first.status in ("todo", "ready") and second.status in ("todo", "ready")
        assert ids[0] in kb.parent_ids(conn, ids[1])


def test_fanout_is_idempotent(kanban_home):
    with kbc.connect() as conn:
        root = _create_root(conn)
    kids = [{"title": "only child"}]
    with kbc.connect() as conn:
        first = fanout_mission_task(conn, root, children=kids)
    assert first is not None
    with kbc.connect() as conn:
        assert fanout_mission_task(conn, root, children=kids) is None


def test_fanout_missing_root_returns_none(kanban_home):
    with kbc.connect() as conn:
        assert fanout_mission_task(conn, "no-such-task", children=[{"title": "x"}]) is None


def test_fanout_empty_children_returns_none(kanban_home):
    with kbc.connect() as conn:
        root = _create_root(conn)
    with kbc.connect() as conn:
        assert fanout_mission_task(conn, root, children=[]) is None

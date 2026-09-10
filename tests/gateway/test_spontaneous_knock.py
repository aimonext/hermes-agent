"""Tests for the spontaneous-knock hook core."""
from __future__ import annotations
import random
import time
import pytest
from gateway.builtin_hooks import spontaneous_knock as sk


def test_idle_seconds_none_is_zero():
    assert sk.idle_seconds(None) == 0.0


def test_idle_seconds_measures_gap():
    assert sk.idle_seconds(100.0, now=160.0) == 60.0


def test_too_soon_no_knock():
    assert sk.should_spontaneous_knock(idle_secs=60.0) is False


def test_too_long_no_knock():
    assert sk.should_spontaneous_knock(idle_secs=99999.0) is False


def test_idle_window_knocks_with_zero_skip():
    rng = random.Random(0)
    assert sk.should_spontaneous_knock(idle_secs=3600.0, skip_probability=0.0, rng=rng) is True


def test_full_skip_never_knocks():
    rng = random.Random(0)
    assert sk.should_spontaneous_knock(idle_secs=3600.0, skip_probability=1.0, rng=rng) is False

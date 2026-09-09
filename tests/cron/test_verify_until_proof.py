"""Tests for cron.verify_until_proof — the mission verification loop."""

from __future__ import annotations

import pytest

from cron.verify_until_proof import (
    ProofConfig,
    backoff_delay,
    next_step,
    run_proof_check,
)


def test_from_job_none_without_script():
    assert ProofConfig.from_job({}) is None
    assert ProofConfig.from_job({"proof_check": "  "}) is None


def test_from_job_defaults_and_bounds():
    cfg = ProofConfig.from_job({"proof_check": "check.py"})
    assert cfg is not None
    assert (cfg.max_iterations, cfg.base_interval) == (3, 300)
    cfg = ProofConfig.from_job(
        {"proof_check": "c.py", "proof_max_iterations": 0, "proof_base_interval": -5}
    )
    assert cfg is not None
    assert (cfg.max_iterations, cfg.base_interval) == (1, 1)


def test_backoff_linear_then_capped():
    assert backoff_delay(300, 1) == 300
    assert backoff_delay(300, 2) == 600
    assert backoff_delay(300, 9) == 600


def test_next_step_done_on_proof():
    cfg = ProofConfig.from_job({"proof_check": "c.py"})
    assert cfg is not None
    decision, delay, _ = next_step(cfg, attempt=1, proof_found=True)
    assert (decision, delay) == ("done", 0)


def test_next_step_rerun_then_escalate():
    cfg = ProofConfig.from_job(
        {"proof_check": "c.py", "proof_max_iterations": 3, "proof_base_interval": 300}
    )
    assert cfg is not None
    decision, delay, _ = next_step(cfg, attempt=1, proof_found=False)
    assert decision == "rerun" and delay == 600
    decision, delay, reason = next_step(cfg, attempt=3, proof_found=False)
    assert decision == "escalate" and delay == 0
    assert "human" in reason


def test_run_proof_check_found(tmp_path):
    script = tmp_path / "proof.py"
    script.write_text("print('proof_found=True')\n")
    res = run_proof_check(str(script))
    assert res.found is True


def test_run_proof_check_missing_marker(tmp_path):
    script = tmp_path / "proof.py"
    script.write_text("print('not yet')\n")
    res = run_proof_check(str(script))
    assert res.found is False


def test_run_proof_check_missing_file():
    res = run_proof_check("/no/such/proof.py")
    assert res.found is False
    assert "not found" in res.evidence


def test_run_proof_check_never_raises(tmp_path):
    script = tmp_path / "boom.py"
    script.write_text("raise SystemExit(3)\n")
    res = run_proof_check(str(script))
    assert res.found is False

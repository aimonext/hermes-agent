"""Verify-until-proof loop for mission cron jobs (mission system Phase 2).

A mission job declares *how its result is proven* instead of hoping one run
is enough::

    job["proof_check"] = "scripts/proofs/breakfast_eaten.py"
    job["proof_max_iterations"] = 3        # hard limit, default 3
    job["proof_base_interval"] = 300       # seconds, default 300 (5 min)

After each run the proof script executes (no shell, timeout-guarded). It
must print ``proof_found=True`` on success. :func:`next_step` then decides::

    "done"     — proof found, stop rerunning.
    "rerun"    — no proof yet, attempts remain; returns backoff delay.
    "escalate" — attempts exhausted; a human must step in.

Backoff is linear (base * attempt) capped at 600s, so a job retries after
~5 then ~10 minutes and escalates on the 3rd miss — matching the mission
plan's "verify until proof, then ask a human" contract. State is explicit:
callers pass the attempt count in and persist whatever ``next_step``
returns; this module keeps no globals and touches no scheduler internals.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

DEFAULT_MAX_ITERATIONS = 3
DEFAULT_BASE_INTERVAL = 300
MAX_INTERVAL = 600
PROOF_MARKER = "proof_found=True"


@dataclass(frozen=True)
class ProofConfig:
    """Provenance for one verification loop, parsed from a cron job dict."""

    script: str
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    base_interval: int = DEFAULT_BASE_INTERVAL

    @classmethod
    def from_job(cls, job: dict) -> Optional["ProofConfig"]:
        script = (job.get("proof_check") or "").strip() if isinstance(job, dict) else ""
        if not script:
            return None
        try:
            max_iterations = int(job.get("proof_max_iterations", DEFAULT_MAX_ITERATIONS))
        except (TypeError, ValueError):
            max_iterations = DEFAULT_MAX_ITERATIONS
        try:
            base_interval = int(job.get("proof_base_interval", DEFAULT_BASE_INTERVAL))
        except (TypeError, ValueError):
            base_interval = DEFAULT_BASE_INTERVAL
        return cls(
            script=script,
            max_iterations=max(1, max_iterations),
            base_interval=max(1, base_interval),
        )


@dataclass(frozen=True)
class ProofResult:
    found: bool
    evidence: str


def run_proof_check(script: str, *, workdir: Optional[str] = None, timeout: int = 60) -> ProofResult:
    """Execute a proof script (file path, no shell) and look for the marker.

    Never raises: missing/unreadable scripts, timeouts, and non-zero exits
    all mean "no proof", with the reason captured as evidence.
    """
    if not script or not os.path.isfile(script):
        return ProofResult(False, f"proof script not found: {script!r}")
    try:
        proc = subprocess.run(
            [sys.executable, script] if script.endswith(".py") else [script],
            cwd=workdir or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProofResult(False, f"proof script timed out after {timeout}s: {script!r}")
    except OSError as exc:
        return ProofResult(False, f"proof script failed to start: {exc}")
    output = (proc.stdout or "") + (proc.stderr or "")
    if PROOF_MARKER in output:
        return ProofResult(True, output.strip()[-2000:])
    return ProofResult(
        False,
        f"exit={proc.returncode} without marker; output tail: {output.strip()[-500:]}",
    )


def backoff_delay(base_interval: int, attempt: int) -> int:
    """Linear backoff (base * attempt) capped at :data:`MAX_INTERVAL`."""
    return min(MAX_INTERVAL, max(1, base_interval) * max(1, attempt))


def next_step(cfg: ProofConfig, *, attempt: int, proof_found: bool) -> tuple[str, int, str]:
    """Decide what happens after attempt number ``attempt`` (1-based).

    Returns ``(decision, delay_seconds, reason)`` where decision is one of
    ``"done"``, ``"rerun"``, ``"escalate"``.
    """
    if proof_found:
        return "done", 0, f"proof found on attempt {attempt}"
    if attempt >= cfg.max_iterations:
        return (
            "escalate",
            0,
            f"no proof after {attempt} attempt(s); needs a human",
        )
    delay = backoff_delay(cfg.base_interval, attempt + 1)
    return "rerun", delay, f"no proof on attempt {attempt}; retry in {delay}s"

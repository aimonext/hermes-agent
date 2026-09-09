# Mission System Implementation Plan

The mission system provides a structured, hierarchical framework for task management, verification, and proactive AI engagement, leveraging Hermes' existing core infrastructure (cron/scheduler, kanban, and skills).

## 1. Architectural Overview
The system follows a three-tier hierarchy:
1. **Mission:** The top-level goal (e.g., "Aimon's daily routine optimization").
2. **Tasks:** Decomposed steps required to achieve the mission (e.g., "Wake up Aimon", "Verify breakfast").
3. **Execution/Verification:** Result-driven cron jobs that verify state until proof is provided.

## 2. Core Components

### A. Mission Control (Kanban Dispatcher)
- Missions and their decomposed tasks will be managed using the existing `kanban` infrastructure.
- Missions are boards; tasks are tickets with a defined `execution_script` or `verification_logic`.
- The `kanban` dispatcher (running within the gateway) will handle task assignment and agent spawning.

### B. Adaptive Scheduling (Cron)
- The existing `cron/scheduler.py` will serve as the engine.
- Mission tasks are scheduled as `cronjobs` with:
    - **verification_until_proof:** Jobs designed to rerun until specific conditions (or "proof" files/evidence) are met.
    - **Context chaining:** Use `context_from` to pass output from verification scripts (e.g., "Aimon did not answer message") into the next task's prompt (e.g., "Knock again, more urgently").

### C. Proactive Engagement ("Knocks")
- Implement a "Knock System" using a randomized cron-ticker pattern.
- The agent will trigger spontaneous `knock` check-ins that inject system-state updates or mission-verification requests into the current conversation (or a new session).
- Logic: `cronjob` with randomized jitter (`every 2-4h`) that checks mission status and sends a message if action is required.

## 3. Implementation Roadmap

### Phase 1: Task Decomposition & Kanban Integration
- Define the mission schema within `mission-system-examples.md`.
- Extend `kanban` CLI tools to support hierarchical task linking (`kanban_link`).
- Enable task fan-out where one mission ticket spawns multiple smaller task tickets.

### Phase 2: Verification Loop
- Implement `verify_until_proof` job type in `cron/scheduler.py`:
    - Rerun interval: 5–10 mins (dynamic backoff).
    - Hard limit: 3 iterations before task escalation (requesting human help/feedback).
    - Success condition: Validation script must return `proof_found=True`.

### Phase 3: Proactive Knock Engine
- Create a `mission_monitor` cron job.
- This job will run asynchronously to the main conversation.
- If mission progress is stagnant, the monitor will trigger a spontaneous "knock" (via `platforms/adapter.send_message`), asking for current status.

## 4. Design Invariants & Safety
- **State Isolation:** Each mission board is a hard isolation boundary (`HERMES_KANBAN_BOARD`).
- **No Over-subscription:** Adhere to the 3-minute hard interrupt for cron sessions.
- **Verification Integrity:** Verification scripts must operate in `skip_memory=True` environments to ensure objective evidence collection.
- **Human-in-the-loop:** Any task failing the retry limit (default 2) must be flagged for human intervention (escalation), preventing autonomous spin loops.

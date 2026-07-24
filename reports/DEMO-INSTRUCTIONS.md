# Demo Instructions — Schedules Feature

These instructions are for Roman to verify that the Schedules feature works end to end.

## Goal
Show that a schedule can be created, saved, and later surfaced as a working follow-up flow.

## What you need
- Letta Desktop open on this machine
- Access to the **Schedules** tab
- A local checkout of this repo

## Step-by-step demo

1. Open Letta Desktop.
2. Navigate to the **Schedules** tab.
3. Create a simple schedule such as:
   - Title: `Roman demo brief`
   - Message: `Check the scheduled follow-up and confirm it appears later.`
   - Timing: choose a near-future time or a recurring daily slot.
4. Save the schedule.
5. Confirm the new schedule appears in the list of active schedules.
6. Run the local demo script from the repo root to simulate the scheduled follow-up:

   ```powershell
   python F:\dt-home\meta\scheduled_demo.py --task brief --source roman-demo
   ```

7. Review the output and confirm it prints:
   - a brief summary
   - the saved brief path
   - a heartbeat-state confirmation line
8. Check the local artifacts that prove the demo ran:
   - `F:\dt-home\meta\.scheduled-demo.log`
   - `F:\dt-home\meta\.scheduled-demo-brief.json`
   - `F:\dt-home\meta\heartbeat-step-health.jsonl`
9. Reopen the **Schedules** tab and confirm the schedule still exists if it was created as recurring.
10. If needed, run the log-only mode to show the background evidence path:

    ```powershell
    python F:\dt-home\meta\scheduled_demo.py --task log --source roman-demo
    ```

## What Roman should observe
- The schedule can be created without external services.
- The demo script produces a local brief and evidence line.
- The heartbeat state file receives a JSONL summary record.
- The feature behaves like a dependable follow-up mechanism rather than a one-off note.

## Suggested talking points
- Schedules make Letta proactive instead of purely reactive.
- The demo is local-first and does not depend on paid tooling.
- The heartbeat record provides a visible integration point for operational checks.

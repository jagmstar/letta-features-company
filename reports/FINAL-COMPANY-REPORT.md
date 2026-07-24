# Final Company Report — Schedules Feature

**Repository:** `jagmstar/letta-features-company`  
**Issue:** #32  
**Feature selected:** Schedules  
**Role:** tech-writer  
**Date:** 2026-07-24

## Executive summary

Company 4 selected **Schedules** because it was the strongest cross-company recommendation and the clearest way to make the twin proactive instead of purely reactive. The feature turns reminders, follow-ups, and recurring checks into a dependable workflow that returns at the right time with the original context.

The implementation is deliberately local-first and demo-friendly. Across the issue trail, the team validated the hidden-task path, the schedule demo script, the installer wiring, and the supporting documentation. The main remaining work is hardening: tighten file permissions, remove latent shell-concatenation risk, and reconcile the documented CLI surface with the machine’s actual availability.

## Feature selected: Schedules

Schedules let Letta hold onto a task, reminder, or recurring check and bring it back later automatically. This was the best option because:

- it had the strongest cross-company signal in the feature-selection thread
- it has obvious day-to-day value for Roman
- it is easy to explain in a demo
- it already had a practical implementation path in the local environment

In short: **Schedules are the feature that makes Letta feel proactive.**

## What was built

| Commit | Deliverable | Notes |
|---|---|---|
| `69a490c5` | Core Schedules implementation | Referenced in the SEDO report as the implementation commit for `meta/scheduled_demo.py`, `meta/install-schedule-demo.ps1`, and the test coverage that exercises the demo flow. |
| `539fb3b` | `reports/schedules-demo-slide.md` | Added the one-page Schedules demo slide. |
| `4f0c092` | `README.md` | Documented the Schedules feature, access paths, and why it matters. |
| `a99edae` | `reports/DEMO-INSTRUCTIONS.md` | Added the step-by-step demo instructions for Roman. |

Supporting planning and tracking artifacts were also created in the reports directory, including the Schedules milestone tracker and deployment notes used by the internal lanes.

## Test results

Validation was performed with free/local resources only.

### Passed checks

- `python tests/test_global_framework.py` ✅
- `python meta/scheduled_demo.py --task log --source smoke` ✅
- `python meta/scheduled_demo.py --task brief --source smoke` ✅
- `powershell -NoProfile -File F:\dt-home\meta\_block10_query.ps1` ✅
- `powershell -NoProfile -ExecutionPolicy Bypass -File F:\dt-home\meta\install-schedule-demo.ps1 -SmokeTest` ✅
- `python -m unittest tests.test_global_framework.GlobalFrameworkTests.test_schedule_demo_installer_is_tied_to_the_python_demo_script` ✅
- `python -m unittest tests.test_global_framework.GlobalFrameworkTests.test_schedules_demo_script_logs_timestamps_to_an_isolated_file` ✅

### Additional runtime evidence

- `python F:\dt-home\meta\scheduled_demo.py --source qao-specialist-2 --task brief` produced a brief and saved evidence locally.
- `python F:\dt-home\meta\scheduled_demo.py --source qao-specialist-3 --task log` confirmed the log-only path.
- `letta cron --help` returned `No such command 'cron'`, which is a documented gap in the CLI surface.

## Security review

Security review outcome: **PASS with hardening required**.

### Positive findings

- The task is hidden in Task Scheduler.
- The task runs through `pythonw.exe`, so it does not open a visible console window.
- The principal is not elevated; the XML shows `InteractiveToken` and no elevated run level.
- No literal secrets were found in the reviewed files.

### Risks to address

- Several schedule-related files and directories are writable by broad local groups; that is too permissive for schedule state or any secret-bearing payload.
- `dt-hidden.vbs` uses shell concatenation and leaves a latent command-injection surface if schedule values ever become user-controlled.
- The schedule/log artifacts should treat host, user, and message content as sensitive and redact environment variables, API keys, and command lines before writing.
- Writes into shared directories should canonicalize paths and reject traversal or reparse-point abuse.

### Conclusion

The current feature is safe enough for a local demo and issue handoff, but it should not be treated as fully production-hardened until the permissions and wrapper risks are fixed.

## Department contributions

1. **Feature Selection** — compared research across companies and selected Schedules as the best product wedge.
2. **SEDO: Implementation Review** — confirmed the schedules demo flow already existed in the implementation path.
3. **SEDO: Installer/Ops** — validated the Task Scheduler registration contract and the smoke path.
4. **SEDO: QA** — added regression coverage for the schedules demo and installer wiring.
5. **SEDO: Code Review** — aligned the tests with current hook and installer APIs.
6. **SEDO: Release Validation** — ran both demo modes locally and confirmed the feature works in practice.
7. **QAO: Config / Availability** — verified the schedule definitions were ready and windowless.
8. **QAO: Positive Runtime** — exercised the brief path and confirmed local evidence was written.
9. **DevOps** — re-registered the scheduled task, enabled hidden execution, and confirmed installer smoke tests passed.
10. **Security** — audited ACLs, wrapper behavior, and artifact handling; identified the remaining hardening work.

## Demo instructions

1. Open Letta Desktop.
2. Navigate to the **Schedules** tab.
3. Create a schedule such as:
   - Title: `Roman demo brief`
   - Message: `Check the scheduled follow-up and confirm it appears later.`
   - Timing: choose a near-future time or a recurring daily slot.
4. Save the schedule and confirm it appears in the active list.
5. Run the local demo from the repo root:

   ```powershell
   python F:\dt-home\meta\scheduled_demo.py --task brief --source final-demo
   ```

6. Confirm the output includes a brief summary, the saved brief path, and a heartbeat-state confirmation line.
7. Check the local evidence files:
   - `F:\dt-home\meta\.scheduled-demo.log`
   - `F:\dt-home\meta\.scheduled-demo-brief.json`
   - `F:\dt-home\meta\heartbeat-step-health.jsonl`
8. Optionally run log-only mode to show the background evidence path:

   ```powershell
   python F:\dt-home\meta\scheduled_demo.py --task log --source final-demo
   ```

## Next steps

- Tighten filesystem ACLs on schedule state and evidence artifacts.
- Replace shell-based wrapper behavior in `dt-hidden.vbs` with a safer launch path.
- Reconcile the documented `letta cron` CLI with the actual machine surface.
- Add one end-to-end UI smoke test for the Schedules tab.
- Refresh the demo screenshots and handoff notes if the UI changes again.

---

Report prepared for issue #32.

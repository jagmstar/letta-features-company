# letta-features-company
AI twin company: research, select and implement unknown Letta Desktop features

## Schedules

Schedules are Letta's time-based follow-up feature: you save a reminder, check-in, or recurring task now, and Letta brings it back later at the right time.

### What it does

- Holds reminders, follow-ups, and recurring checks until the scheduled time
- Turns a one-off chat request into a workflow that returns automatically later
- Fits best for daily briefs, inbox triage, status notes, and accountability loops

### How to access

- Desktop app: **Schedules** tab
- CLI: `letta cron add`, `letta cron list`, `letta cron delete`
- Agent workflows: create schedule entries as part of an automation flow

### Why it matters

- Makes Letta proactive instead of only reactive
- Reduces missed follow-ups and manual tracking
- Pairs well with Memory and background agents

### Example

> “Remind me tomorrow at 9 AM to review the rollout plan.”

Letta stores the reminder, then resurfaces it at the right time with the original context.

### Notes

- Local research indicates the scheduling / cron surface is documented and intended for proactive follow-up flows.
- The Windows hidden-task path has been verified elsewhere in this repo for scheduled jobs that should not open a visible window.
- Treat the CLI path as something to verify on the current machine before relying on it for critical automation.


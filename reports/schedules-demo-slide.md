# Schedules
### Letta’s time-based follow-up feature for Roman

**Tagline:** _“Set it now, get it back at the right time.”_

## What it does
Schedules let Letta hold onto a task, reminder, or follow-up and bring it back later automatically.
Instead of relying on Roman to remember, the system remembers the deadline and reactivates the right action when the time arrives.

## How it works
1. **Roman creates a schedule** — e.g. “Remind me tomorrow at 9:00 AM to send the status note.”
2. **Letta stores the job** — target time, message, and any needed context.
3. **The scheduler wakes up later** — when the deadline hits, it triggers the saved action.
4. **Letta delivers the follow-up** — Roman gets the reminder or task as a normal assistant response.

## Why it matters
- Turns one-off chats into **reliable workflows**
- Reduces missed follow-ups and manual tracking
- Pairs well with **memory** and **background agents**
- Makes Letta feel proactive, not just reactive

## Demo script
**User:** “Roman, remind me tomorrow at 9 AM to review the rollout plan.”  
**System:** Schedule is created.  
**Later:** Letta resurfaces the reminder at 9 AM with the original context.

## Current note
Local research shows the scheduling / cron surface is documented, but the CLI path still needs hardening before it can be treated as fully reliable.

**Bottom line:** Schedules are the feature that turns Letta into a dependable follow-up engine for Roman.

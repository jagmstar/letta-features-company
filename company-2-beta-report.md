# Company 2 (Beta) Research Report

Issue: #14  
Repository: `jagmstar/letta-features-company`  
Prepared by: Tech Writer  
Date: 2026-07-23

## Scope

This report compiles the Company 2 findings gathered in issues #8-#13 and consolidates them into one decision-ready view for the Beta company track.

Assumption: when the earlier research says a feature is “not currently used by Clark,” it means the feature was not visible in the current twin workflow or in the docs review used for this investigation.

## Executive summary

Company 2’s strongest opportunity is to turn the Letta Desktop / Letta Code stack from a reactive chat experience into a proactive operating system for Roman’s twin workflow.

The recurring pattern across the research is:

- **Memory** keeps the twin coherent and auditable.
- **Schedules / heartbeats** make the twin act over time instead of only on demand.
- **Skills and custom slash commands** package repeatable work into reusable actions.
- **Local providers, hooks, and lifecycle events** keep the setup Windows-friendly and free/local.
- **Statusline, panels, and mod UI** improve operator visibility and workflow control.

## Feature table

| Feature | Access path | Value | Effort | Demo idea |
| --- | --- | --- | --- | --- |
| Memory viewer + history | `/memory` in the CLI or the Memory page in the desktop app | Makes memory drift visible and lets the twin inspect or repair long-lived context | Medium | Open memory history, edit a block, and show the change persists |
| `/doctor` memory audit | CLI slash command | Audits token use and memory placement; useful for cleanup after long sessions | Low | Run `/doctor` on a messy memory tree and show the improved layout |
| Schedules / heartbeats | Desktop `Schedules` tab or `letta cron add/list/delete` | Gives the twin proactive follow-ups, recurring check-ins, and timed rituals | Medium | Schedule a daily brief and show it appear in the schedule list |
| Channels | Channel surfaces plus external platform setup | Supports team orchestration and multi-channel interaction when linked correctly | Medium to High | Route one helper conversation through a connected channel |
| Skills | `/skills`, skill import/install, `.skills/`, or `~/.letta/skills/` | Turns repeatable company workflows into reusable playbooks | Medium | Import a `roman-briefing` skill and invoke it on a new issue |
| Custom slash commands | `.commands/*.md` or `~/.letta/commands/*.md` | Lowest-friction way to turn recurring prompts into one-tap workflows | Low | Add `/daily-brief` or `/meeting-prep` and run it end to end |
| Statusline customization | `/statusline` and the local statusline extension surface | Keeps active role, mode, or goal visible at all times | Low to Medium | Show a custom statusline with role, goal, and approval state |
| Panels / transient mod UI | Mod UI surfaces such as `openPanel()` | Useful for approvals, checklists, and task-specific UI without cluttering chat history | Medium | Open a checklist panel for kickoff and close it after approval |
| Local mod tools | `letta.tools.register(...)` or equivalent local tool registration | Lets the model call local capabilities directly | Medium | Add a workspace-health tool that summarizes branch or file status |
| Local provider mods | Local provider registration / model connection surfaces | Enables local-only or free model options for privacy and cost control | Medium | Run the same workflow against a local Ollama-style model |
| Lifecycle / turn / tool events | Event hooks such as conversation, turn, tool, compact, and LLM events | Enables orchestration, logging, and guardrails around twin activity | Medium | Log each turn and emit a summary after the conversation closes |
| Permission overlays / hooks | Hook and permissions settings | Adds safety controls before tools run; useful for guardrails and QA | Medium | Block dangerous shell commands before execution |
| Agent-to-agent messaging / hidden conversations | `letta -p --from-agent ...` and related agent messaging surfaces | Lets the twin coordinate with helper agents without exposing clutter to the main flow | Medium | Use a hidden helper conversation for research verification |
| Desktop preferences | Desktop preference settings / local preferences file | Makes the environment reproducible across machines and sessions | Low | Change theme or default working directory and show the preference persists |

## Top recommendation

**Ship Schedules / heartbeats, paired with the Memory viewer.**

Why this wins:

- It best expresses the “proactive twin” vision.
- It creates visible value beyond a passive assistant.
- Memory keeps the twin coherent; schedules make it act.
- It is the clearest architectural fit from the Company 2 review.

## Best first increment

If the team wants a faster first win before the full proactive layer lands, start with **custom slash commands**.

They are the lowest-effort way to package repeatable workflows, and they give the company a tangible operator gain while the richer proactive features are being built.

## Recommended rollout order

1. Memory viewer + `/doctor`
2. Custom slash commands
3. Schedules / heartbeats
4. Skills
5. Statusline customization
6. Local provider support and hooks
7. Defer heavier mod UI and broader channel work until the feature surface is fully validated

## Source trail

Findings were consolidated from the Company 2 issue chain:

- Issue #8: Research lead findings and final recommendation
- Issue #9: UI / menus deep-dive
- Issue #10: Skills / mods / commands deep-dive
- Issue #11: Architecture fit review
- Issue #12: QA completeness check
- Issue #13: Windows and local/free feasibility review


# Company 1 (Alpha) Research Report

**Issue:** [#7](https://github.com/jagmstar/letta-features-company/issues/7)

## Executive summary

Company 1вЂ™s research points to a clear pattern: the highest-value Letta Desktop / Letta Code features for the Roman twin company are the ones that make the agent more proactive, more reusable, and easier to operate.

The strongest recommendation is **Schedules**. It is the cleanest way to turn the twin into a system that acts later without constant prompting. The next best set of features is **Skills / mods / custom commands**, which create reusable company workflows. **Channels** is also important because it brings the twin into the places where work already happens.

## Scope and sources

This report consolidates the findings from the Company 1 issue set:

- **#2** Letta Desktop UI / menus research
- **#3** Skills, mods, commands, providers, and hooks research
- **#4** Architecture fit review
- **#5** QA completeness review
- **#6** Windows / local-model feasibility review

## Consolidated findings

### What stands out most

- **Schedules** unlock the most obvious вЂњassistant that acts laterвЂќ behavior.
- **Skills and mods** are the best foundation for repeatable company processes.
- **Channels** make the twin reachable inside real collaboration tools.
- **Memory view** and **statusline** are low-effort operator wins.
- **Lifecycle hooks** are powerful, but also the easiest way to create hidden complexity.
- **Windows + local/free models** are feasible for the core surfaces, with paid/cloud dependencies being the main constraint.

## Feature table

| Name | Access path | Value | Effort | Demo idea | Top recommendation |
|---|---|---|---|---|---|
| Memory view | Desktop app sidebar **Memory**; or `/memory` in CLI | Keep company facts, people, policies, and decisions visible instead of scattered across chat history | Small (0.5вЂ“1 day) | Teach one policy, then show the memory structure update and inspection flow | Nice follow-up |
| Schedules | Sidebar **Schedules**; or `letta cron`; or create via agent workflow | Best fit for proactive reminders, briefings, and recurring checks | Medium (1вЂ“2 days) | 9:00 daily briefing plus recurring inbox triage | **Top recommendation** |
| Channels | Sidebar **Channels / Connections**; or `letta channels configure` | Bring the twin into Slack, Telegram, Discord, WhatsApp, or Signal where work already happens | MediumвЂ“large (2вЂ“4 days) | Connect one Slack thread and have the twin respond with status updates | High-priority follow-up |
| Skills | Skills page в†’ Add skill в†’ Import from GitHub; also `/skills`, `/skill-name`, `/skill-creator` | Package repeatable workflows like meeting prep, triage, and reporting | Medium (1вЂ“2 days) | Import a вЂњmeeting triageвЂќ skill and run it on a real thread | High-priority follow-up |
| Statusline | `/statusline`; global file at `~/.letta/extensions/statusline.tsx` | Give a constant at-a-glance footer for model, context, and next action | Small (a few hours) | Footer shows company mode, model, and next scheduled task | Good visibility win |
| Panels / ADE | `/ade` or Letta Desktop ADE view | Make memory, tools, and prompts debuggable before workflows scale | Medium (1вЂ“2 days) | Change a memory block live and show the simulator plus memory state update | Useful for debugging |
| Slash commands | Type `/` and use Tab autocomplete; project-local `.commands/` or `~/.letta/commands/` | Turn recurring SOPs into one-word commands the team can standardize | SmallвЂ“medium (0.5вЂ“2 days) | `/daily-brief`, `/meeting-summary`, `/handoff-check` | Strong operator convenience |
| Mods / mod UI | `letta mods list|enable|disable|update|remove|package` | Ship reusable harness behavior for policy gates, reminders, or UI tweaks | Medium (1вЂ“3 days) | Package a mod that injects a company status reminder | Strong follow-on option |
| Local providers | `/connect` and `/model` | Keep the workflow local/offline and avoid paid API dependence | SmallвЂ“medium (a few hours to tune) | Route mechanical checks to Ollama and reserve deeper reasoning for stronger models | Feasibility enabler |
| Lifecycle hooks | `~/.claude/settings.json` or project `.claude/settings.json` | Enforce proof, auto-check subagents, and snapshot state before compaction | Small for one hook; medium for a safe chain | Reject a subagent вЂњdoneвЂќ if the diff is empty; snapshot open items before compaction | Powerful but higher-risk |

## Recommendation ranking

1. **Schedules** вЂ” highest leverage for RomanвЂ™s proactive assistant goal.
2. **Skills / mods** вЂ” best foundation for repeatable team workflows.
3. **Channels** вЂ” essential for real-world communication intake and response.
4. **Memory view / statusline** вЂ” low-cost operator wins.
5. **Slash commands / hooks / local providers** вЂ” useful infrastructure, best treated as enablers.

## Feasibility notes for Company 1

- The **Windows desktop app** path is feasible.
- Core surfaces such as **Memory view**, **slash commands**, and **local models** should work without paid APIs.
- **Skills**, **mods**, and many forms of automation are platform-agnostic once their dependencies are installed.
- Cloud-only or paid dependencies should be treated as out of scope for the вЂњlocal/free modelвЂќ baseline.
- The QA review flagged a documentation gap: the research is broad enough, but several items still need concrete screenshots or docs citations before they should be considered fully proven.

## Bottom line

If Company 1 can only push one feature first, it should be **Schedules**.

If the team can deliver a second wave, the best pairing is **Skills / mods** for reusable workflows, followed by **Channels** for real-world intake and collaboration.

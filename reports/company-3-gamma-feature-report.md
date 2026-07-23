# Company 3 (Gamma) — Letta Desktop Feature Research Report

**Issue:** #21  
**Repository:** `jagmstar/letta-features-company`  
**Prepared by:** Tech Writer  
**Date:** 2026-07-23

## Executive summary

Company 3’s research shows that Letta Desktop / Letta Code is already strongest in three areas:

1. **Memory** — multiple memory layers are available and operational.
2. **Orchestration** — skills, background reflection, and multi-agent routing create a strong workflow engine.
3. **Extensibility** — bridge/API access and local agent surfaces make it possible to wire the system into broader automation.

The biggest practical gap is not raw capability, but **packaging and reliability**. The current mega-skill is too large, the skill catalog is missing a few important workflow helpers, and some surfaces are documented but not yet cleanly usable.

## What the team found

- The memory stack is real: core memory blocks, archival memory, and git-backed MemFS all exist.
- The skills system is powerful, but the current `ai-sdlc` skill is too large to be dependable.
- Background reflection and sleep-time compute are active and useful for consolidation.
- A live HTTP bridge exists, but it should be hardened with a better health probe.
- A scheduler/crons channel is described, but the CLI path is not currently usable.
- The best near-term demo value comes from memory + skill-driven automation, not from adding more surface area.

## Feature table

| Feature | Access path | Value | Effort | Demo idea |
|---|---|---:|---:|---|
| Core memory blocks | In-context blocks such as `persona.md`, `human.md`, `active-lessons.md`, and `tasks.md` | High | Low | Show how the assistant keeps identity, goals, and current work in persistent blocks across turns. |
| Archival memory | Letta server archival search / memory index | High | Medium | Search a keyword like `voice` and show that relevant historical passages can be retrieved, even when the live context is small. |
| MemFS git-backed memory | Agent memory filesystem under the Letta agent directory | High | Low | Edit a memory note, then show the git diff and commit history proving memory changes are versioned. |
| Skills system | Skill files and trigger flow; current mega-skill is `ai-sdlc` | High | Medium | Trigger a skill, then show why the system is easier to trust when the skill is split into smaller, focused modules. |
| Missing workflow skills | QA cycle, GitHub workflow, and self-check skills | High | Medium | Add one tiny self-check skill and use it to verify a completed task before handoff. |
| Reflection / background agents | Sleep-time compute and background reflection worktrees | Medium-High | Medium | Let a background pass consolidate lessons from a session and write them back into memory. |
| Search | `meta/letta_mem.py search "<term>"` | High | Low | Run a search on a known topic and compare the returned passages against the current session notes. |
| Server agents | Local role agents exposed on the Letta server | High | Medium | Message a role-specific agent such as CTO or CFO and compare how focused its answer is versus a general chat. |
| HTTP bridge | `meta/letta_bridge.py` / `/v1/agents/` on the discovered local bridge port | High | Low | Demonstrate a successful bridge probe and a minimal API call that proves the bridge is alive. |
| Multi-agent coordination | Orchestrator + shared memory/files/comments/API | High | Medium | Split one task across three agents, then show the orchestrator collecting and reconciling the outputs. |
| Scheduling / crons | `crons.json` channel and the documented cron path | Medium | High | Show a scheduled reminder or background job if the CLI path is restored; currently this is more of a roadmap feature. |
| Tools / MCP / custom functions | No MCP servers and no custom functions are currently connected | Medium | High | Add one simple external tool integration and demonstrate a real input/output flow that the assistant cannot do by itself. |

## Priority ranking

### 1) Skills system cleanup
The highest-leverage feature is the skills system because it controls how Letta turns capability into repeatable behavior. The current `ai-sdlc` skill exists, but it is too large to be a dependable operational surface.

### 2) Memory + versioning
The memory stack is the clearest proof that Letta can act like a persistent partner. MemFS plus archival memory creates a strong story for continuity, traceability, and recovery.

### 3) Orchestration and automation
Reflection, server agents, and the HTTP bridge make the platform useful beyond one-off chat. These features should be shown as a coordinated workflow rather than as isolated curiosities.

## Top recommendation

**Split the mega-skill into smaller skills and add the missing QA / GitHub workflow / self-check skills first.**

Why this is the best recommendation:

- It directly addresses the biggest reliability issue found in the research.
- It improves every downstream workflow, not just one demo.
- It makes the system easier to test, easier to explain, and easier to maintain.
- It pairs naturally with the existing memory and bridge features, which are already strong.

## Secondary recommendations

1. **Harden the HTTP bridge** with a real health probe before caching a port.
2. **Clarify or repair the cron path** so the documented scheduling surface matches reality.
3. **Expose memory health metrics** such as index size, passage count, and stale-hit ratio.
4. **Use one end-to-end demo flow** that shows memory, a skill trigger, and a role agent in the same story.

## Suggested demo narrative

A good Company 3 demo would be:

1. Start with a short user task.
2. Write the task into memory.
3. Trigger a focused skill.
4. Let a background/reflection step capture the lesson.
5. Use the bridge or a server agent to verify the system is alive.
6. Show the git-backed memory change as proof of persistence.

That sequence tells the strongest story: **Letta remembers, acts, verifies, and improves over time.**

## Sources used

- Company 3 research notes and audit findings
- Local Letta capability audit
- Live repository and documentation review


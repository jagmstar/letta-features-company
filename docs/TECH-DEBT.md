# Technical Debt Register

This register captures the debt called out in the architecture review and orders it by what should be resolved first to support the roadmap.

| Order | Technical debt item | Priority | Effort | Impact | Why it is in this position |
| --- | --- | --- | --- | --- | --- |
| 1 | File-based shared state | P0 | L | High | This is the main blocker to durability, concurrency, and horizontal scale. |
| 2 | Minimal auth model | P0 | M | High | Static API keys and permissive CORS are not suitable for broader exposure. |
| 3 | No persistent volume in Compose | P1 | S | Medium | Without persistence, state and evidence can disappear on restart. |
| 4 | Duplicate parsing logic across API / dashboard / demo | P1 | M | High | Multiple readers of the same files make schema changes fragile and expensive. |
| 5 | Limited schema validation | P1 | M | Medium | The system relies too much on convention and basic JSON parsing. |
| 6 | Dashboard deployment depends on pre-generated HTML | P1 | S | Medium | Deployments can drift from source if regeneration is missed. |
| 7 | Observability via files only | P1 | M | Medium | There are no metrics or centralized logs for production-style operations. |
| 8 | Global handler state in `SchedulesHTTPRequestHandler` | P2 | S | Medium | This complicates lifecycle management and multi-instance reasoning. |
| 9 | Docker image omits demo/runtime helper scripts | P2 | S | Low | Container behavior diverges from local repo behavior and limits portability. |

## Recommended resolution order
1. **File-based shared state** and **minimal auth model** are the first blockers to address.
2. **Persistent volume support** should follow immediately so state survives restarts while a shared store is designed.
3. **Duplicate parsing logic** and **limited schema validation** should be consolidated before the skills manifest work expands.
4. **Dashboard regeneration in CI/CD** should be automated before broader rollout.
5. **Observability** should be upgraded before channels and multimodal traffic increase system load.
6. **Global handler state** should be removed as part of the move toward cleaner multi-instance operation.
7. **Docker image completeness** should be fixed once the runtime contract stabilizes.

## Notes
- The P0 items are the ones most likely to block the Q3 foundation work.
- The P1 items mostly affect reliability and maintainability during the Q4/Q1 expansion.
- The P2 items are important cleanup items, but they do not block the next product surface on their own.

# Technical Roadmap for `letta-features-company`

## Planning premise
This roadmap assumes the current schedules stack remains the delivery backbone while the product expands into skills, channel integrations, and multimodal capabilities. The existing file-backed runtime is acceptable for the current demo and internal workflow, but it must be progressively hardened before the next product surfaces ship at scale.

## Current state

### What is built
- **Runtime API:** `api/schedules_api.py` exposes health, schedule listing, schedule detail, log access, status, and manual run endpoints.
- **Scheduler/demo workers:** `meta/scheduled_demo.py` produces brief snapshots and evidence logs; `meta/production_scheduler.py` supports periodic meta tasks.
- **Dashboard generation:** `dashboard/generate_dashboard.py` renders a static dashboard from the latest brief and log files.
- **Delivery pipeline:** GitHub Actions handle CI and deployment to Pages.
- **Packaging/runtime:** Docker and Compose support local runtime execution.

### What works today
- API requests are authenticated with `X-API-Key`.
- Per-IP rate limiting is in place.
- Request metadata is logged to disk.
- Health checks are exposed over HTTP.
- Schedules can be inspected and triggered manually.
- The dashboard can be generated from current files and served statically.
- Deployment copies the generated dashboard artifact into GitHub Pages.

### What is tested today
- The CI workflow runs the Python test suite on pushes and pull requests.
- `pytest` covers the main API surface.
- `tests/test_kill_tests.py` covers negative/kill-path behavior.
- Recent fixes validated JSON handling and missing-dashboard-file behavior.
- Documentation accuracy has also been verified in recent history.

### Current limitations
- Shared state is file-based and not horizontally scalable.
- The API uses a hand-rolled standard-library server instead of a framework.
- Dashboard deployment depends on a pre-generated HTML artifact.
- Demo, API, and dashboard code each interpret the same files independently.
- Security controls are demo-grade rather than production-grade.

## Q3 2026 goals: Skills platform foundation

### Features
- Deliver the **Skills library** with search, filter, loading, empty, and error states.
- Add **skill detail views** with description, version, source, permissions, supported tools, and usage examples.
- Implement **install from catalog or link** with validation and progress feedback.
- Add **enable, disable, uninstall, and assign-to-agent** workflows.
- Store skill state per user and per agent.
- Introduce **audit logging** for install and lifecycle actions.

### Technical debt to address
- Define a **versioned skill manifest schema** and shared parser.
- Remove duplicated parsing/formatting logic between API, dashboard, and demo code.
- Add contract tests for skill metadata and installation responses.
- Introduce schema validation for install payloads and skill metadata.

### Infrastructure work
- Add a persistent storage abstraction for skill state and audit records.
- Move secret handling out of demo defaults and require runtime configuration.
- Regenerate dashboard artifacts in CI so deployments do not rely on stale checked-in HTML.
- Expand test fixtures to cover install/enable/disable/uninstall edge cases.

### Metrics
- Skill install success rate above **95%** for valid sources.
- Median time from discovery to install under **2 minutes**.
- At least **70%** of installed skills assigned to an agent within 24 hours.
- Less than **2%** of installs fail due to validation or schema errors.

## Q4 2026 goals: Team distribution and channel integrations

### Features
- Ship channel integrations for **Slack, Telegram, Discord, and custom channels**.
- Support a single persistent agent identity across multiple channels.
- Add message routing for text and basic multimodal payloads.
- Surface channel-level access controls and delivery status.
- Add skill update/rollback and shared/team import flows where the Q3 foundation is stable.

### Technical debt to address
- Externalize runtime state from flat files into a shared datastore or durable volume-backed service.
- Introduce a queue/worker boundary for inbound channel events and long-running tasks.
- Harden the auth model with narrower CORS and clearer secret rotation behavior.
- Add structured logs and first-class operational metrics instead of file-only inspection.

### Infrastructure work
- Build webhook ingestion and event delivery adapters for each channel.
- Add secrets management for channel tokens, API keys, and webhook signing material.
- Stand up integration test sandboxes for channel-specific verification.
- Add retry, backoff, and dead-letter handling for channel message delivery.

### Metrics
- Channel connection success rate above **90%**.
- End-to-end delivery latency below **2 seconds** for standard text messages at the p95.
- Message delivery failure rate below **2%** for supported channels.
- At least **1 team** using a shared agent across **2+ channels**.

## Q1 2027 goals: Built-in image generation and multimodal delivery

### Features
- Add built-in **image generation** and **image modification** flows.
- Support asset preview, history, and re-use in the desktop UI.
- Deliver generated images through channels alongside text responses.
- Provide a clear permission and provenance model for generated media.
- Make multimodal tasks feel like a first-class agent capability rather than an external add-on.

### Technical debt to address
- Finish packaging consistency so local, container, and CI behavior match more closely.
- Eliminate remaining global handler state that complicates multi-instance execution.
- Remove dependency on manual dashboard regeneration and close the loop in CI/CD.
- Complete observability work with metrics around generation latency, failures, and queue depth.

### Infrastructure work
- Add a media asset store or object-storage-backed cache for generated files.
- Introduce provider abstraction for image-generation vendors and test doubles.
- Add rate limiting and quotas for expensive multimodal requests.
- Add regression tests for media delivery in desktop and channel flows.

### Metrics
- Image generation success rate above **95%** for valid requests.
- Median time to first image under **60 seconds** for standard provider-backed flows.
- At least **50%** of generated assets reused or shared through a second surface.
- Multimodal task failure rate below **3%** after validation.

## Feature dependencies
1. **Skills management** is the foundation for skill manifests, per-agent assignment, and permission scoping.
2. **Channel integrations** depend on a stable agent capability registry, audit logging, and secure delivery controls.
3. **Image generation** depends on the same capability/permission model, plus media storage and channel delivery support.
4. **Persistent state and secrets management** must land before the product can reliably scale beyond the current demo-grade file system.
5. **Schema validation and shared parsing** should be in place before skill updates, team sharing, and multimodal payloads are exposed to users.
6. **Observability and CI-generated artifacts** should be implemented before broader rollout so failures can be detected quickly.

## Risk matrix

| Risk | Likelihood | Impact | Mitigation | Early warning signal |
| --- | --- | --- | --- | --- |
| File-backed state corrupts or diverges under higher write volume | High | High | Move state to a durable shared store, add atomic writes, and test concurrent updates | Increasing log-file conflicts or lost schedule/skill events |
| Skill schema changes break installs or updates | Medium | High | Version the manifest schema, centralize parsing, and add contract tests | Install failures after minor metadata changes |
| Channel provider instability or rate limits cause delivery gaps | Medium | High | Use adapter layers, retries, and provider-specific test sandboxes | Message backlog growth or repeated webhook failures |
| Security exposure from broad permissions or weak defaults | Medium | High | Tighten auth, narrow CORS, validate sources, and log sensitive actions | Unknown installs or unexpected capability exposure |
| Multimodal latency and cost exceed expectations | Medium | Medium | Use provider abstraction, quotas, async processing, and caching | Long queue depth or rising per-request spend |

## Resource requirements

| Quarter | Agents | Compute | Storage |
| --- | --- | --- | --- |
| Q3 2026 | 2 implementation agents + 1 QA/automation agent | Standard CI runners, 2-4 vCPU per job, no GPU required | 10-20 GB for state, fixtures, and artifacts |
| Q4 2026 | 3 implementation agents + 1 platform/QA agent | 4-8 vCPU integration environments plus webhook sandboxes | 20-40 GB for logs, channel fixtures, and test data |
| Q1 2027 | 4 implementation agents + 1 platform/observability agent | Standard CI plus optional GPU access or external provider test doubles | 50-100 GB for media assets, caches, and audit logs |

## Roadmap summary
- **Q3 2026:** ship skills management as the first productized workflow.
- **Q4 2026:** expand the product to team channels and persistent cross-surface usage.
- **Q1 2027:** add image generation and round out the platform with operational hardening.

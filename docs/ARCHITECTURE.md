# Schedules Feature Architecture

## Scope
This document describes the current architecture of the `letta-features-company` repository as implemented today. The system is centered on a schedules demo/API, a dashboard generator, supporting scheduler scripts, and GitHub Actions-based delivery.

## System architecture overview

The repository implements a small, file-backed operational system with four main concerns:

1. **Runtime API** – `api/schedules_api.py` exposes schedule data and manual execution endpoints over HTTP.
2. **Schedule/demo workers** – `meta/scheduled_demo.py` builds the brief snapshot and appends evidence lines; `meta/production_scheduler.py` provides a configurable periodic runner for meta tasks.
3. **Dashboard rendering** – `dashboard/generate_dashboard.py` reads the latest brief/log files and renders a static HTML dashboard.
4. **Delivery pipeline** – GitHub Actions test, package, and deploy the feature; Docker and Compose support local runtime packaging.

The design is intentionally lightweight: it avoids a database and queue, and instead uses files under `meta/` as the shared system of record.

### Key runtime characteristics
- **State is file-based**: logs, brief snapshots, and heartbeat records live on disk.
- **The API is synchronous**: requests are handled directly in a single Python process using the standard library HTTP server.
- **The dashboard is static output**: the dashboard generator produces `dashboard/index.html` from current files.
- **Scheduler logic is local**: periodic work is handled by Python scripts rather than an external job runner.

## Component diagram

```text
                          +-----------------------------+
                          |        GitHub Actions       |
                          |  CI / Deploy / Artifacts     |
                          +--------------+--------------+
                                         |
                                         v
                          +-----------------------------+
                          |      GitHub Pages Site      |
                          |  dashboard/index.html       |
                          +-----------------------------+
                                         ^
                                         |
                           deploy copies generated HTML
                                         |
+------------------+     reads/writes    +-----------------------------+
| scheduled_demo.py |<------------------>|         meta/ files         |
| production_sched. |                    | .scheduled-demo.log         |
| (periodic tasks)  |                    | .scheduled-demo-brief.json  |
+---------+--------+                    | heartbeat-step-health.jsonl  |
          |                             | scheduler.log                |
          |                             +--------------+--------------+
          |                                            ^
          |                                            |
          |                                            | reads
          v                                            |
+-----------------------------+                         |
|     schedules_api.py        |-------------------------+
| HTTP API + auth + rate      | writes request logs
| limiting + schedule control  |
+--------------+--------------+
               |
               | exposes JSON over HTTP
               v
+-----------------------------+
|   Clients / operators       |
|  curl, tests, dashboards    |
+-----------------------------+

                           +-----------------------------+
                           | dashboard/generate_dashboard|
                           |  static HTML builder        |
                           +--------------+--------------+
                                          |
                                          | reads log + brief snapshot
                                          v
                                   +-------------+
                                   | dashboard/  |
                                   | index.html  |
                                   +-------------+
```

## Data flow diagram

```text
1) Demo / scheduler execution
   inbox/team-status/voice-health inputs
                |
                v
   scheduled_demo.py builds brief JSON
                |
                +--> writes meta/.scheduled-demo-brief.json
                +--> appends meta/.scheduled-demo.log
                +--> appends meta/heartbeat-step-health.jsonl
                |
                v
   production_scheduler.py can invoke the demo and other tasks on an interval

2) API access and manual execution
   client -> schedules_api.py
                |
                +--> authenticate via X-API-Key
                +--> rate-limit by client IP
                +--> log request metadata to meta/.schedules-api-requests.log
                |
                +--> GET /api/health returns service health
                +--> GET /api/schedules returns schedule registry
                +--> GET /api/schedules/{name} returns schedule details
                +--> GET /api/schedules/{name}/log returns recent log entries
                +--> GET /api/schedules/{name}/status returns runtime state
                +--> POST /api/schedules/{name}/run triggers a schedule
                |
                v
   run_schedule() updates in-memory state and appends schedule evidence

3) Dashboard generation
   dashboard/generate_dashboard.py
                |
                +--> reads meta/.scheduled-demo.log
                +--> reads meta/.scheduled-demo-brief.json
                |
                v
   dashboard/index.html (static artifact)
                |
                v
   GitHub Pages / local nginx container serves the dashboard
```

## Technology stack

### Language and runtime
- **Python 3.12**
- Standard library only for the core implementation:
  - `http.server` for the API
  - `threading` and `RLock` for in-process safety
  - `dataclasses` for runtime models
  - `json`, `pathlib`, `subprocess`, `datetime`, `statistics`, `html`, and `re` for data handling

### Web and presentation
- **Static HTML/CSS/JS** generated by `dashboard/generate_dashboard.py`
- **GitHub Pages** for published dashboard hosting
- **nginx:1.27-alpine** in `docker-compose.yml` for local static file serving

### Delivery and packaging
- **Docker** for API containerization
- **Docker Compose** for local multi-service orchestration
- **GitHub Actions** for CI and Pages deployment

### Test tooling
- `pytest` for the main CI suite
- `unittest`-style tests in `tests/test_kill_tests.py`

## Design decisions and trade-offs

### 1. File-backed state instead of a database
**Decision:** Use files in `meta/` as the shared state boundary.

**Benefits**
- Very low operational overhead
- Easy to inspect and debug manually
- Works well for a small feature with mostly append-only data

**Trade-offs**
- Not ideal for concurrent writers
- Hard to scale horizontally
- Recovery and retention are manual concerns

### 2. Standard-library HTTP server instead of a framework
**Decision:** Implement the API with `BaseHTTPRequestHandler` / `ThreadingHTTPServer`.

**Benefits**
- Minimal dependencies
- Simple packaging
- Clear control over request/response behavior

**Trade-offs**
- More boilerplate than FastAPI/Flask/etc.
- No automatic OpenAPI/spec generation
- Error handling, routing, and validation are hand-rolled

### 3. Static dashboard generation
**Decision:** Render one HTML file from the latest data snapshot.

**Benefits**
- Fast to serve
- Easy to deploy to GitHub Pages
- No runtime dependency on the API server

**Trade-offs**
- The dashboard is only as fresh as the last generation step
- Any data model changes require regeneration
- Interactivity is limited to client-side display helpers

### 4. Demo-friendly fallback behavior
**Decision:** `schedules_api.py` attempts to load `meta/scheduled_demo.py`, but can still operate with built-in fallback behavior when that module is unavailable.

**Benefits**
- Container image can stay small
- Local demo files are optional at runtime
- The API remains usable even if the demo script is absent

**Trade-offs**
- Behavior can differ between local development and container deployment
- Some outputs become synthetic/fallback rather than fully generated by the demo module

### 5. Simple guardrails instead of a full security stack
**Decision:** Use a static API key, per-IP rate limiting, and request logging.

**Benefits**
- Easy to understand and maintain
- Good enough for a controlled demo environment

**Trade-offs**
- Not suitable for multi-tenant or internet-facing production use without hardening
- CORS is permissive
- Secret rotation and auth lifecycle are manual

## Security architecture

### Current controls
- **API key authentication** via `X-API-Key`
- **Per-IP rate limiting** with a fixed window and maximum request count
- **Request logging** that records path, client IP, auth presence, status, and latency
- **Invalid JSON rejection** before running schedules
- **CORS headers** are explicitly set for browser access

### Security gaps / caveats
- The default API key is a demo value unless overridden by `SCHEDULES_API_KEY`
- CORS allows `*`, which is acceptable for a demo but weak for production
- Logs are written in plaintext on disk
- No TLS termination is handled in-process
- No role-based access control, token expiration, or secret rotation workflow exists
- No input schema enforcement beyond basic JSON parsing for the run endpoint

### Security posture summary
This is a **demo-grade security model** suitable for controlled environments, local development, or internal use. It should be hardened before exposure to untrusted users or shared infrastructure.

## Deployment architecture

### Local development
- `Dockerfile` builds a minimal Python 3.12 image for the API.
- `docker-compose.yml` runs:
  - `api` on port `8290`
  - `dashboard` via nginx on port `8080`
- The dashboard container serves `./dashboard` as static content.

### CI
- `.github/workflows/ci.yml` runs on pushes to `main` and pull requests.
- It installs test dependencies and runs the full test suite.
- It also publishes JUnit artifacts for the API and kill tests.

### CD / Pages deployment
- `.github/workflows/deploy.yml` runs after successful CI on `main` or via manual dispatch.
- It copies `dashboard/index.html` into a Pages artifact and deploys it.
- The workflow does **not** regenerate the dashboard, so the checked-in HTML artifact must already be current.

### Packaging observation
The current Docker image only copies the `api/` directory. That keeps the image small, but it also means the demo/scheduler scripts and dashboard generator are not part of the API image unless added separately.

## Scaling considerations

### Current bottlenecks
1. **Single-process execution** – the API relies on in-process state and locks.
2. **Shared filesystem state** – all components coordinate through files.
3. **No queue or worker separation** – schedule execution happens synchronously in request handlers or local scripts.
4. **Manual dashboard regeneration** – freshness depends on when the HTML is rebuilt.

### What will break first
- Multiple API replicas would fight over the same files unless the storage layer is redesigned.
- High write rates would stress the append-only log files and the log parsing logic.
- Long-running schedule jobs would block request threads if executed directly in the API path.

### Scale-out path
If this feature grows, the likely progression is:
1. Move state from flat files to a shared datastore.
2. Split execution into a background worker/queue model.
3. Generate the dashboard from a versioned API response or materialized view.
4. Replace the hand-rolled HTTP server with a framework that better supports routing, validation, and observability.

## Technical debt register

| Item | Impact | Why it matters |
| --- | --- | --- |
| File-based shared state | High | Limits concurrency, durability, and horizontal scaling. |
| Duplicate parsing logic across API / dashboard / demo | High | Changes to log formats or brief schemas must be coordinated manually. |
| Global handler state in `SchedulesHTTPRequestHandler` | Medium | Makes lifecycle management and multi-instance behavior harder to reason about. |
| Dashboard deployment depends on pre-generated HTML | Medium | Stale or missing artifacts can slip into Pages deployments. |
| Minimal auth model | High | Static API key and wildcard CORS are not enough for stronger security requirements. |
| Limited schema validation | Medium | The system relies on convention more than explicit contracts. |
| Observability via files only | Medium | There are no metrics, traces, or centralized logs. |
| Docker image omits demo/runtime helper scripts | Medium | Container behavior diverges from local repo behavior. |
| No persistent volume in compose | Medium | Restarting containers can lose schedule evidence and brief state. |

## Improvement recommendations

### Priority 1 — Externalize state and secrets
**Why:** This is the largest blocker to reliability and scale.

**Recommended changes**
- Move schedule state, logs, and snapshots into a persistent shared store.
- Introduce a secret management path for the API key.
- Add a volume or storage abstraction for local/runtime persistence.

### Priority 2 — Define a shared schedule schema and reduce duplication
**Why:** The API, demo script, and dashboard all interpret the same data independently.

**Recommended changes**
- Introduce a single data model for schedule events and brief snapshots.
- Centralize log formatting and parsing.
- Add contract tests for the generated JSON and log lines.

### Priority 3 — Automate dashboard regeneration in CI/CD
**Why:** Deployment currently trusts a pre-generated artifact.

**Recommended changes**
- Run `dashboard/generate_dashboard.py` in CI or during deploy.
- Fail the deployment if the generated output differs from the committed artifact.
- Publish the generated dashboard directly from the pipeline.

### Priority 4 — Harden security defaults
**Why:** The current controls are fine for a demo, but not for wider exposure.

**Recommended changes**
- Replace the default API key with a required runtime secret.
- Narrow CORS to known origins.
- Add request authentication/authorization beyond a single static key.

### Priority 5 — Improve observability and operational safety
**Why:** The system currently has little insight beyond file inspection.

**Recommended changes**
- Emit structured logs to stdout in addition to files.
- Add basic metrics around schedule runs, API errors, and rate limiting.
- Introduce health/readiness endpoints for deployment checks.

### Priority 6 — Make the runtime packaging consistent
**Why:** Local and container behavior should match more closely.

**Recommended changes**
- Include the demo/scheduler helpers in the image when needed.
- Add a persistent `meta/` volume in Compose.
- Document the differences between demo mode and container mode.

## Summary
The repository is best understood as a compact schedules platform with a shared file-based state layer, a small authenticated HTTP API, a script-driven scheduler, and a static dashboard. The current implementation is good for demos and internal use, but it will need stronger persistence, schema discipline, and deployment automation before it can behave like a production-grade service.

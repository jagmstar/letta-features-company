# Schedules Feature Documentation

## Project overview

Schedules make Letta proactive instead of purely reactive. The feature lets a user save a reminder, follow-up, or recurring task now and surface it later with the original context.

This repository documents and exercises the schedules stack through five cooperating pieces:

- `F:\dt-home\meta\scheduled_demo.py` — creates the local demo evidence (`brief` or `log`), writes the schedule log, brief snapshot, and heartbeat record
- `F:\dt-home\meta\production_scheduler.py` — production-style scheduler that loads task definitions from JSON and executes built-in jobs safely
- `F:\dt-home\letta-features-company\api\schedules_api.py` — HTTP API for listing schedules, checking status, running schedules, and reading log entries
- `F:\dt-home\letta-features-company\dashboard\generate_dashboard.py` — static dashboard generator that turns the local log and brief snapshot into an HTML status page
- `F:\dt-home\letta-features-company\tests\test_kill_tests.py` — regression tests for invalid inputs, malformed config, and missing files

The implementation is local-first and demo-friendly. The API, dashboard, and scheduler all read and write the same small set of files under `F:\dt-home\meta`, which keeps the feature easy to validate without external services.

## Architecture diagram

```text
                            +----------------------------+
                            |     Letta Desktop UI       |
                            |      Schedules tab         |
                            +-------------+--------------+
                                          |
                                          v
                          +---------------+----------------+
                          |   scheduled_demo.py           |
                          |  - --task brief               |
                          |  - --task log                 |
                          |  writes evidence files        |
                          +---------------+----------------+
                                          |
                 +------------------------+------------------------+
                 |                        |                        |
                 v                        v                        v
     +----------------------+   +----------------------+   +----------------------+
     | .scheduled-demo.log   |   | .scheduled-demo-    |   | heartbeat-step-      |
     | schedule evidence     |   | brief.json          |   | health.jsonl         |
     +-----------+----------+   +-----------+----------+   +-----------+----------+
                 |                          |                          |
                 +--------------------------+--------------------------+
                                            |
                                            v
                          +-----------------+------------------+
                          |   schedules_api.py                 |
                          |  /api/health                       |
                          |  /api/schedules                    |
                          |  /api/schedules/{name}/...         |
                          |  request log -> .schedules-api...  |
                          +-----------------+------------------+
                                            |
                                            v
                          +-----------------+------------------+
                          | dashboard/generate_dashboard.py    |
                          | builds dashboard/index.html        |
                          +-----------------+------------------+
                                            |
                                            v
                            +---------------+----------------+
                            | GitHub Pages or nginx static    |
                            | dashboard/index.html            |
                            +--------------------------------+

                          +----------------------------------+
                          | production_scheduler.py          |
                          | JSON config -> task registry     |
                          | built-in jobs -> demo scripts    |
                          +----------------------------------+
```

## Installation guide

### 1) Prerequisites

- Python 3.12 recommended
- Git
- Optional: Docker and Docker Compose for containerized deployment

### 2) Clone the repository

```powershell
git clone <your-repo-url>
cd F:\dt-home\letta-features-company
```

### 3) Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If you use `cmd.exe`, activate with:

```bat
.\.venv\Scripts\activate.bat
```

### 4) Install the Python dependencies used by the feature and tests

```powershell
python -m pip install --upgrade pip pytest requests
```

### 5) Generate local schedule evidence

The dashboard and API are easiest to validate after the demo evidence files exist.

Run the brief path first:

```powershell
python F:\dt-home\meta\scheduled_demo.py --task brief --source setup
```

If you want the evidence-only path as well:

```powershell
python F:\dt-home\meta\scheduled_demo.py --task log --source setup
```

These commands create or update:

- `F:\dt-home\meta\.scheduled-demo.log`
- `F:\dt-home\meta\.scheduled-demo-brief.json`
- `F:\dt-home\meta\heartbeat-step-health.jsonl`

### 6) Build the dashboard

```powershell
python F:\dt-home\letta-features-company\dashboard\generate_dashboard.py
```

This writes `F:\dt-home\letta-features-company\dashboard\index.html`.

### 7) Start the API server

```powershell
python F:\dt-home\letta-features-company\api\schedules_api.py --host 0.0.0.0 --port 8290
```

If you want to override the API key and request log path:

```powershell
python F:\dt-home\letta-features-company\api\schedules_api.py `
  --host 0.0.0.0 `
  --port 8290 `
  --api-key your-secret-key `
  --request-log-path F:\dt-home\meta\.schedules-api-requests.log
```

### 8) Verify everything is working

Check the health endpoint first:

```powershell
curl http://localhost:8290/api/health
```

Then list schedules with the API key header:

```powershell
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules
```

Open the generated dashboard file in a browser:

```text
F:\dt-home\letta-features-company\dashboard\index.html
```

## API documentation

### Common API conventions

- Base URL: `http://localhost:8290`
- API prefix: `/api`
- Content type: JSON (`application/json; charset=utf-8`)
- Authentication header: `X-API-Key`
- Default API key: `letta-schedules-demo-key` unless `SCHEDULES_API_KEY` or `--api-key` overrides it
- Rate limit: 10 requests per 60 seconds per client IP for `GET` and `POST` routes
- CORS: enabled for all origins (`Access-Control-Allow-Origin: *`)

### Error format

All structured errors return the same shape:

```json
{
  "error": {
    "code": "invalid_api_key",
    "message": "Invalid API key",
    "status": 403
  }
}
```

Common error codes:

- `missing_api_key` — the `X-API-Key` header was not provided
- `invalid_api_key` — the provided key was incorrect
- `rate_limit_exceeded` — the client exceeded the request window
- `invalid_json` — request body could not be parsed as JSON
- `not_found` — endpoint path was not recognized
- `task_not_found` — schedule name was unknown
- `method_not_allowed` — wrong HTTP method for the route
- `internal_server_error` — unexpected server failure

### Built-in schedules

The API currently exposes two built-in schedules through `ScheduleStore`:

| Name | Description | Purpose |
|---|---|---|
| `brief` | Build a local inbox and team-status brief, then persist a snapshot. | Creates the main demo brief and updates the dashboard data. |
| `log` | Append a schedule evidence line and heartbeat record without generating a brief snapshot. | Exercises the evidence-only path. |

### `GET /api/health`

Health check for the service. This route does **not** require an API key.

**Example request**

```powershell
curl http://localhost:8290/api/health
```

**Example response**

```json
{
  "status": "ok",
  "service": "schedules-api",
  "version": "2.0.0",
  "started_at": "2026-07-24T10:00:00+00:00",
  "uptime_seconds": 12.345,
  "uptime": "0:00:12",
  "schedules": 2,
  "timestamp": "2026-07-24T10:00:12+00:00"
}
```

### `GET /api/schedules`

Returns the available schedules and their current runtime summary.

**Required headers**

```text
X-API-Key: <your-api-key>
```

**Example request**

```powershell
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules
```

**Example response**

```json
{
  "items": [
    {
      "name": "brief",
      "description": "Build a local inbox and team-status brief, then persist a snapshot.",
      "command": "python scheduled_demo.py --task brief",
      "status": "stopped",
      "running": false,
      "run_count": 1,
      "last_run_at": "2026-07-24T10:00:00+00:00"
    },
    {
      "name": "log",
      "description": "Append a schedule evidence line and heartbeat record without generating a brief snapshot.",
      "command": "python scheduled_demo.py --task log",
      "status": "stopped",
      "running": false,
      "run_count": 1,
      "last_run_at": "2026-07-24T10:00:02+00:00"
    }
  ],
  "count": 2
}
```

### `GET /api/schedules/{name}`

Returns a detailed view of a single schedule.

**Examples**

```powershell
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules/brief
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules/log
```

**Example response**

```json
{
  "name": "brief",
  "description": "Build a local inbox and team-status brief, then persist a snapshot.",
  "command": "python scheduled_demo.py --task brief",
  "source_script": "F:\\dt-home\\meta\\scheduled_demo.py",
  "status": "stopped",
  "running": false,
  "run_count": 3,
  "last_run_at": "2026-07-24T10:01:00+00:00",
  "recent_logs": [
    {
      "timestamp": "2026-07-24T10:01:00+00:00",
      "task": "brief",
      "source": "api",
      "host": "testhost",
      "user": "testuser",
      "pid": 123,
      "detail": "inbox=1; voice=ok"
    }
  ],
  "last_log": {
    "timestamp": "2026-07-24T10:01:00+00:00",
    "task": "brief",
    "source": "api",
    "host": "testhost",
    "user": "testuser",
    "pid": 123,
    "detail": "inbox=1; voice=ok"
  },
  "paths": {
    "log": "F:\\dt-home\\meta\\.scheduled-demo.log",
    "brief": "F:\\dt-home\\meta\\.scheduled-demo-brief.json",
    "heartbeat": "F:\\dt-home\\meta\\heartbeat-step-health.jsonl"
  },
  "latest_snapshot": {
    "timestamp": "2026-07-24T10:01:00+00:00",
    "summary": "inbox=1; voice=ok"
  }
}
```

### `GET /api/schedules/{name}/log`

Returns the parsed log entries for a schedule.

**Example request**

```powershell
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules/brief/log
```

**Example response**

```json
{
  "name": "brief",
  "count": 3,
  "entries": [
    {
      "timestamp": "2026-07-24T10:01:00+00:00",
      "task": "brief",
      "source": "api",
      "host": "testhost",
      "user": "testuser",
      "pid": 123,
      "detail": "inbox=1; voice=ok"
    }
  ]
}
```

### `GET /api/schedules/{name}/status`

Returns the current runtime state for a schedule.

**Example request**

```powershell
curl -H "X-API-Key: letta-schedules-demo-key" http://localhost:8290/api/schedules/brief/status
```

**Example response**

```json
{
  "name": "brief",
  "status": "stopped",
  "running": false,
  "run_count": 3,
  "last_run_at": "2026-07-24T10:01:00+00:00"
}
```

### `POST /api/schedules/{name}/run`

Triggers a manual schedule run.

**Required headers**

```text
X-API-Key: <your-api-key>
Content-Type: application/json
```

The request body may be empty, but if you send a body it must be valid JSON.

**Example request**

```powershell
curl -X POST `
  -H "X-API-Key: letta-schedules-demo-key" `
  -H "Content-Type: application/json" `
  http://localhost:8290/api/schedules/brief/run
```

**Example response**

```json
{
  "name": "brief",
  "status": "stopped",
  "running": false,
  "triggered": true,
  "run_count": 4,
  "last_run_at": "2026-07-24T10:02:00+00:00",
  "result": {
    "brief": {
      "summary": "inbox=2; needs_llm=1; surface=0; teams_online=3/3; voice=ok"
    },
    "snapshot_path": "F:\\dt-home\\meta\\.scheduled-demo-brief.json",
    "detail": "inbox=2; needs_llm=1; surface=0; teams_online=3/3; voice=ok"
  }
}
```

**Invalid JSON example**

```powershell
curl -X POST `
  -H "X-API-Key: letta-schedules-demo-key" `
  -H "Content-Type: application/json" `
  --data "{\"broken\": true," `
  http://localhost:8290/api/schedules/brief/run
```

This returns `400 invalid_json`.

### `OPTIONS /api/*`

The server responds to CORS preflight requests and advertises these headers:

- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: GET, POST, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, Authorization, X-API-Key`
- `Access-Control-Max-Age: 86400`

## Configuration guide

### `scheduled_demo.py`

Command-line options:

- `--source` — label written into the log line; useful for separating manual runs from scheduler runs
- `--task {brief,log}` — choose the action
  - `brief` reads the inbox and team-status files, writes the snapshot, and logs evidence
  - `log` only appends the evidence line and heartbeat record

Files used by the demo script:

- reads: `F:\dt-home\inbox\_proactive.md`
- reads: `F:\dt-home\inbox\team-status-report.json`
- writes: `F:\dt-home\meta\.scheduled-demo.log`
- writes: `F:\dt-home\meta\.scheduled-demo-brief.json`
- writes: `F:\dt-home\meta\heartbeat-step-health.jsonl`

### `production_scheduler.py`

Command-line options:

- `--config` — path to `scheduler_config.json`
- `--dry-run` — report what would run without executing tasks

Configuration format:

```json
{
  "log": {
    "path": "scheduler.log",
    "max_lines": 1000
  },
  "tasks": [
    {
      "name": "health_check",
      "interval_seconds": 300,
      "function": "health_check",
      "enabled": true
    },
    {
      "name": "brief_generator",
      "interval": 900,
      "function": "brief_generator"
    }
  ]
}
```

Supported task fields:

- `name` — unique task name
- `interval_seconds` or `interval` — positive number of seconds between runs
- `function` — registry key for the function to execute
- `enabled` — optional boolean, defaults to `true`

Built-in function registry keys:

- `health_check`
- `brief_generator`
- `inbox_processor`
- `voice_health_check`

Log rotation is limited by `max_lines` and defaults to 1000 lines.

### `schedules_api.py`

Command-line options:

- `--host` — bind address, default `0.0.0.0`
- `--port` — bind port, default `8290`
- `--api-key` — value required in the `X-API-Key` header
- `--request-log-path` — where the JSONL request log is written

Environment variable:

- `SCHEDULES_API_KEY` — default API key if `--api-key` is not supplied

Default paths used by the API:

- request log: `F:\dt-home\meta\.schedules-api-requests.log`
- demo log: `F:\dt-home\meta\.scheduled-demo.log`
- brief snapshot: `F:\dt-home\meta\.scheduled-demo-brief.json`
- heartbeat: `F:\dt-home\meta\heartbeat-step-health.jsonl`

### `dashboard/generate_dashboard.py`

The dashboard generator expects both of these files to exist:

- `F:\dt-home\meta\.scheduled-demo.log`
- `F:\dt-home\meta\.scheduled-demo-brief.json`

It writes `F:\dt-home\letta-features-company\dashboard\index.html`.

The generated dashboard refreshes every 60 seconds and is designed to be served as static content.

## Testing guide

### Run the full test suite

From the repository root:

```powershell
python -m pytest
```

### Run the schedules kill tests

The kill tests are the negative-path regression tests for the Schedules feature. They verify that bad inputs fail cleanly instead of crashing the feature.

```powershell
python -m pytest F:\dt-home\letta-features-company\tests\test_kill_tests.py
```

If you want the standard unittest runner instead:

```powershell
python F:\dt-home\letta-features-company\tests\test_kill_tests.py
```

### What the kill tests cover

- invalid `--task` values for `scheduled_demo.py`
- malformed scheduler JSON config in `production_scheduler.py`
- invalid JSON in `POST /api/schedules/{name}/run`
- missing log file handling in `dashboard/generate_dashboard.py`

### CI test coverage

The CI workflow runs:

- `python -m pytest`
- `python -m pytest api/tests --junitxml=test-results/api-junit.xml`
- `python -m pytest tests --junitxml=test-results/tests-junit.xml`

## Deployment guide

### CI/CD with GitHub Actions

#### Continuous integration

`F:\dt-home\letta-features-company\.github\workflows\ci.yml` runs on:

- push to `main`
- pull requests

It performs these steps:

1. checks out the repository
2. installs Python 3.12
3. upgrades `pip`
4. installs `pytest` and `requests`
5. runs the test suite
6. publishes JUnit artifacts for later review

#### Dashboard deployment

`F:\dt-home\letta-features-company\.github\workflows\deploy.yml` runs:

- automatically after CI succeeds on `main`
- manually through `workflow_dispatch`

Deployment flow:

1. check out the repository
2. copy `dashboard/index.html` into the Pages staging directory
3. upload the GitHub Pages artifact
4. deploy to GitHub Pages

### Docker deployment

The repository includes a minimal API Dockerfile and a Compose file:

- `F:\dt-home\letta-features-company\Dockerfile`
- `F:\dt-home\letta-features-company\docker-compose.yml`

#### Build the API image

```powershell
docker build -t schedules-api .
```

#### Run the API container

```powershell
docker run --rm -p 8290:8290 -e SCHEDULES_API_KEY=letta-schedules-demo-key schedules-api
```

#### Run the full Compose stack

```powershell
docker compose up --build
```

Compose starts:

- the API on port `8290`
- an nginx static site for the dashboard on port `8080`

### Docker notes

- The API image is intentionally small and copies only the `api/` directory.
- If the demo files in `/meta` are not mounted into the container, the API falls back to its built-in schedule behavior.
- Regenerate `dashboard/index.html` before serving the dashboard through nginx or GitHub Pages.

## Troubleshooting

### `401 missing_api_key`

You called a protected route without `X-API-Key`.

Fix:

- add the header
- verify the API key value
- confirm you are using the correct port

### `403 invalid_api_key`

The header was present but incorrect.

Fix:

- check `SCHEDULES_API_KEY`
- check the `--api-key` value used to start the server
- verify there are no extra spaces or quoting mistakes

### `429 rate_limit_exceeded`

The API rate limiter blocked the client IP.

Fix:

- wait for the `Retry-After` period
- reduce request frequency
- test from a separate client IP if needed

### `400 invalid_json`

The request body for `POST /api/schedules/{name}/run` was not valid JSON.

Fix:

- send an empty body, or
- send valid JSON such as `{}`

### Dashboard generation fails with a missing log file

`generate_dashboard.py` requires a log file and a brief snapshot.

Fix:

1. run `python F:\dt-home\meta\scheduled_demo.py --task brief --source fix`
2. confirm the demo log and brief snapshot exist
3. rerun `python F:\dt-home\letta-features-company\dashboard\generate_dashboard.py`

### The dashboard looks stale

Fix:

- rerun the brief demo path to refresh the snapshot
- regenerate `dashboard/index.html`
- verify the browser is opening the freshly written file

### Port 8290 is already in use

Fix:

- stop the process already bound to the port
- start the API on a different port with `--port`
- update any curl or dashboard references to match

### `GET /api/schedules/{name}` returns `404 task_not_found`

The schedule name is not one of the built-in definitions.

Fix:

- use `brief` or `log`
- confirm the store loaded the expected definitions
- check whether a custom store is being used in test code

### Docker container starts but the dashboard is empty

Fix:

- regenerate `dashboard/index.html`
- make sure the compose nginx service is mounting the correct directory
- verify the static file exists before starting the container

## Contributing guide

1. Create a branch from `main`.
2. Make the code or documentation change.
3. Update the schedules docs whenever the API, CLI, or file layout changes.
4. Run the relevant tests, including the kill tests.
5. Regenerate the dashboard if your change affects schedule output.
6. Keep examples consistent with the current command-line behavior and response shapes.
7. Open a pull request with a clear summary of the change and validation steps.

### Documentation expectations

When you change the schedules feature, update these docs together:

- `F:\dt-home\letta-features-company\docs\README.md`
- `F:\dt-home\letta-features-company\reports\DEMO-INSTRUCTIONS.md`
- `F:\dt-home\letta-features-company\README.md` if the high-level feature summary changes

### Writing style

- Prefer exact command examples over vague descriptions
- Show the real file paths and real API routes
- Keep the API examples aligned with the current JSON shapes
- Note failure modes clearly so operators know what to expect

---

This document is intended to be the canonical Schedules reference for developers, testers, and demo operators working in this repository.

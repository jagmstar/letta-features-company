# API Reference

This document describes the HTTP API exposed by `api/schedules_api.py`.

- **Base URL:** `http://localhost:8290`
- **API prefix:** `/api`
- **Content type:** `application/json`

## Authentication

Most endpoints require an API key in the `X-API-Key` header.

```bash
export API_KEY='letta-schedules-demo-key'
```

Example header:

```bash
-H 'X-API-Key: letta-schedules-demo-key'
```

### Notes
- The health endpoint does **not** require authentication.
- The server default API key is `letta-schedules-demo-key` unless `SCHEDULES_API_KEY` or `--api-key` is set.
- Requests without the header return **401** with error code `missing_api_key`.
- Requests with the wrong key return **403** with error code `invalid_api_key`.

## Rate limiting

Protected endpoints are rate limited to **10 requests per 60 seconds per client IP**.

When the limit is exceeded:
- the server returns **429 Too Many Requests**
- the response includes a `Retry-After` header
- the JSON body uses error code `rate_limit_exceeded`

## Error format

All API errors use the same envelope:

```json
{
  "error": {
    "code": "invalid_json",
    "message": "Request body contains invalid JSON",
    "status": 400
  }
}
```

### Common error codes

| HTTP status | Error code | Meaning |
|---|---|---|
| 400 | `invalid_json` | The request body is not valid JSON. |
| 400 | `invalid_channel` | A channel payload failed validation. |
| 400 | `invalid_prompt` | Image prompt validation failed. |
| 401 | `missing_api_key` | `X-API-Key` header was not provided. |
| 403 | `invalid_api_key` | `X-API-Key` did not match the configured key. |
| 404 | `not_found` | The endpoint does not exist. |
| 404 | `task_not_found` | Unknown schedule name. |
| 404 | `channel_not_found` | Unknown channel name. |
| 404 | `image_not_found` | Unknown image id. |
| 405 | `method_not_allowed` | The HTTP method is not allowed on the endpoint. |
| 409 | `channel_disabled` | The target channel exists but is disabled. |
| 429 | `rate_limit_exceeded` | The client exceeded the per-IP rate limit. |
| 500 | `internal_server_error` | Unexpected server failure. |
| 502 | `channel_send_failed` | Channel delivery failed. |
| 502 | `image_generation_failed` | Image generation or editing failed. |

---

## Health

### `GET /api/health`

Returns service health and uptime information. No authentication required.

#### Example

```bash
curl -s http://localhost:8290/api/health
```

#### Example response

```json
{
  "status": "ok",
  "service": "schedules-api",
  "version": "2.0.0",
  "started_at": "2026-07-24T12:00:00+00:00",
  "uptime_seconds": 123.456,
  "uptime": "0:02:03",
  "schedules": 2,
  "timestamp": "2026-07-24T12:02:03+00:00"
}
```

---

## Schedules

The API currently exposes two built-in schedules: `brief` and `log`.

### `GET /api/schedules`

Lists all schedules.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/schedules
```

#### Example response

```json
{
  "count": 2,
  "items": [
    {
      "name": "brief",
      "description": "Build a local inbox and team-status brief, then persist a snapshot.",
      "command": "python scheduled_demo.py --task brief",
      "status": "stopped",
      "running": false,
      "run_count": 0,
      "last_run_at": null
    },
    {
      "name": "log",
      "description": "Append a schedule evidence line and heartbeat record without generating a brief snapshot.",
      "command": "python scheduled_demo.py --task log",
      "status": "stopped",
      "running": false,
      "run_count": 0,
      "last_run_at": null
    }
  ]
}
```

### `GET /api/schedules/{name}`

Returns detailed information about a schedule.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/schedules/brief
```

#### Example response

```json
{
  "name": "brief",
  "description": "Build a local inbox and team-status brief, then persist a snapshot.",
  "command": "python scheduled_demo.py --task brief",
  "source_script": "F:/dt-home/letta-features-company/meta/scheduled_demo.py",
  "status": "stopped",
  "running": false,
  "run_count": 0,
  "last_run_at": null,
  "recent_logs": [],
  "last_log": null,
  "paths": {
    "log": "F:/dt-home/letta-features-company/meta/.scheduled-demo.log",
    "brief": "F:/dt-home/letta-features-company/meta/.scheduled-demo-brief.json",
    "heartbeat": "F:/dt-home/letta-features-company/meta/heartbeat-step-health.jsonl"
  }
}
```

### `GET /api/schedules/{name}/log`

Returns parsed log entries for a schedule.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/schedules/brief/log
```

#### Example response

```json
{
  "name": "brief",
  "count": 0,
  "entries": []
}
```

### `GET /api/schedules/{name}/status`

Returns the runtime state for a schedule.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/schedules/brief/status
```

#### Example response

```json
{
  "name": "brief",
  "status": "stopped",
  "running": false,
  "run_count": 0,
  "last_run_at": null
}
```

### `POST /api/schedules/{name}/run`

Triggers a schedule manually.

- The JSON request body is optional.
- If a body is sent, it must be valid JSON.
- The body is ignored by the server.

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{}' \
  http://localhost:8290/api/schedules/brief/run
```

#### Example response

```json
{
  "name": "brief",
  "status": "stopped",
  "running": false,
  "triggered": true,
  "run_count": 1,
  "last_run_at": "2026-07-24T12:01:00+00:00",
  "result": {
    "brief": {
      "timestamp": "2026-07-24T12:01:00+00:00",
      "source": "api",
      "task": "brief",
      "summary": "inbox=1; voice=ok"
    },
    "snapshot_path": "F:/dt-home/letta-features-company/meta/.scheduled-demo-brief.json",
    "log_line": "2026-07-24T12:01:00+00:00 scheduled-demo task=brief source=api host=localhost user=api pid=0 detail=inbox=1; voice=ok",
    "heartbeat": {
      "status": "ok",
      "task": "brief"
    },
    "detail": "inbox=1; voice=ok"
  }
}
```

---

## Channels

Channel operations support Slack, Telegram, and Discord channel registrations.

### `GET /api/channels`

Lists registered channels.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/channels
```

#### Example response

```json
{
  "count": 2,
  "items": [
    {
      "name": "ops",
      "type": "slack",
      "webhook_url": "https://example.com/ops",
      "enabled": true
    },
    {
      "name": "alerts",
      "type": "discord",
      "webhook_url": "https://example.com/alerts",
      "enabled": true
    }
  ]
}
```

### `POST /api/channels`

Registers a new channel.

#### Request body

```json
{
  "name": "ops",
  "type": "slack",
  "webhook_url": "https://example.com/ops",
  "enabled": true
}
```

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"ops","type":"slack","webhook_url":"https://example.com/ops","enabled":true}' \
  http://localhost:8290/api/channels
```

#### Example response

```json
{
  "name": "ops",
  "type": "slack",
  "webhook_url": "https://example.com/ops",
  "enabled": true
}
```

### `GET /api/channels/{name}`

Returns one channel.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/channels/ops
```

#### Example response

```json
{
  "name": "ops",
  "type": "slack",
  "webhook_url": "https://example.com/ops",
  "enabled": true
}
```

### `DELETE /api/channels/{name}`

Deletes a channel.

#### Example

```bash
curl -s -X DELETE \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/channels/ops
```

#### Example response

```json
{
  "removed": {
    "name": "ops",
    "type": "slack",
    "webhook_url": "https://example.com/ops",
    "enabled": true
  }
}
```

### `POST /api/channels/{name}/send`

Sends a message to one channel.

#### Request body

```json
{
  "message": "Deployment complete"
}
```

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Deployment complete"}' \
  http://localhost:8290/api/channels/ops/send
```

#### Example response

```json
{
  "channel": "ops",
  "type": "slack",
  "enabled": true,
  "message": "Deployment complete",
  "payload": {
    "text": "Deployment complete"
  },
  "response": {
    "status": 200,
    "body": {
      "ok": true
    }
  }
}
```

### `POST /api/channels/broadcast`

Broadcasts a message to all enabled channels.

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"All systems green"}' \
  http://localhost:8290/api/channels/broadcast
```

#### Example response

```json
{
  "message": "All systems green",
  "sent": [
    {
      "channel": "ops",
      "type": "slack",
      "enabled": true,
      "message": "All systems green",
      "payload": {
        "text": "All systems green"
      },
      "response": {
        "status": 200,
        "body": {
          "ok": true
        }
      }
    }
  ],
  "failed": []
}
```

---

## Images

The image API stores generated and edited image records in memory.

### `GET /api/images`

Lists the full image history.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/images
```

#### Example response

```json
{
  "count": 1,
  "items": [
    {
      "image_id": "4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f",
      "operation": "generate",
      "request": {
        "prompt": "A neon city skyline at sunset",
        "size": "1024x1024",
        "style": "cinematic",
        "format": "png"
      },
      "prompt": "A neon city skyline at sunset",
      "size": "1024x1024",
      "style": "cinematic",
      "format": "png",
      "image_data": "mock-image://2edc8a1a8f7e4bbcbcf2b9a5",
      "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
      "generated_with": "mock-placeholder",
      "created_at": "2026-07-24T12:01:00+00:00",
      "source_image_id": null,
      "edit_prompt": null,
      "metadata": {
        "operation": "generate",
        "source_image_id": null,
        "edit_prompt": null,
        "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
        "generated_with": "mock-placeholder"
      }
    }
  ]
}
```

### `GET /api/images/{image_id}`

Returns a stored image record.

#### Example

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  http://localhost:8290/api/images/4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f
```

#### Example response

```json
{
  "image_id": "4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f",
  "operation": "generate",
  "request": {
    "prompt": "A neon city skyline at sunset",
    "size": "1024x1024",
    "style": "cinematic",
    "format": "png"
  },
  "prompt": "A neon city skyline at sunset",
  "size": "1024x1024",
  "style": "cinematic",
  "format": "png",
  "image_data": "mock-image://2edc8a1a8f7e4bbcbcf2b9a5",
  "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
  "generated_with": "mock-placeholder",
  "created_at": "2026-07-24T12:01:00+00:00",
  "source_image_id": null,
  "edit_prompt": null,
  "metadata": {
    "operation": "generate",
    "source_image_id": null,
    "edit_prompt": null,
    "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
    "generated_with": "mock-placeholder"
  }
}
```

### `POST /api/images/generate`

Generates a new image record.

#### Request body

```json
{
  "prompt": "A neon city skyline at sunset",
  "size": "1024x1024",
  "style": "cinematic",
  "format": "png"
}
```

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"A neon city skyline at sunset","size":"1024x1024","style":"cinematic","format":"png"}' \
  http://localhost:8290/api/images/generate
```

#### Example response

```json
{
  "image_id": "4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f",
  "operation": "generate",
  "request": {
    "prompt": "A neon city skyline at sunset",
    "size": "1024x1024",
    "style": "cinematic",
    "format": "png"
  },
  "prompt": "A neon city skyline at sunset",
  "size": "1024x1024",
  "style": "cinematic",
  "format": "png",
  "image_data": "mock-image://2edc8a1a8f7e4bbcbcf2b9a5",
  "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
  "generated_with": "mock-placeholder",
  "created_at": "2026-07-24T12:01:00+00:00",
  "source_image_id": null,
  "edit_prompt": null,
  "metadata": {
    "operation": "generate",
    "source_image_id": null,
    "edit_prompt": null,
    "render_hash": "2edc8a1a8f7e4bbcbcf2b9a5d4d7d6a1c2f7b4d7b7d1b2c3d4e5f6a7b8c9d0e1",
    "generated_with": "mock-placeholder"
  }
}
```

### `POST /api/images/{image_id}/edit`

Edits an existing image. The request may supply `prompt` or `edit_prompt`.

#### Request body

```json
{
  "prompt": "Add a red scarf and glowing eyes"
}
```

#### Example

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Add a red scarf and glowing eyes"}' \
  http://localhost:8290/api/images/4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f/edit
```

#### Example response

```json
{
  "image_id": "9b50fbc3e92c4d62a9d7c2e0f4f1d2a3",
  "operation": "edit",
  "request": {
    "prompt": "Add a red scarf and glowing eyes",
    "size": "1024x1024",
    "style": "cinematic",
    "format": "png"
  },
  "prompt": "Add a red scarf and glowing eyes",
  "size": "1024x1024",
  "style": "cinematic",
  "format": "png",
  "image_data": "mock-image://6dfd8c1b2a3f4c5d6e7f8a9b",
  "render_hash": "6dfd8c1b2a3f4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f00112233445566778899",
  "generated_with": "mock-placeholder",
  "created_at": "2026-07-24T12:02:00+00:00",
  "source_image_id": "4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f",
  "edit_prompt": "Add a red scarf and glowing eyes",
  "metadata": {
    "operation": "edit",
    "source_image_id": "4ef0e7d3d6d04fd8b5f7fb6d4c2e1e6f",
    "edit_prompt": "Add a red scarf and glowing eyes",
    "render_hash": "6dfd8c1b2a3f4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f00112233445566778899",
    "generated_with": "mock-placeholder"
  }
}
```

---

## Quick endpoint summary

| Area | Method | Path |
|---|---|---|
| Health | GET | `/api/health` |
| Schedules | GET | `/api/schedules` |
| Schedules | GET | `/api/schedules/{name}` |
| Schedules | GET | `/api/schedules/{name}/log` |
| Schedules | GET | `/api/schedules/{name}/status` |
| Schedules | POST | `/api/schedules/{name}/run` |
| Channels | GET | `/api/channels` |
| Channels | POST | `/api/channels` |
| Channels | GET | `/api/channels/{name}` |
| Channels | DELETE | `/api/channels/{name}` |
| Channels | POST | `/api/channels/{name}/send` |
| Channels | POST | `/api/channels/broadcast` |
| Images | GET | `/api/images` |
| Images | GET | `/api/images/{image_id}` |
| Images | POST | `/api/images/generate` |
| Images | POST | `/api/images/{image_id}/edit` |

## Typical curl pattern

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  -H 'Content-Type: application/json' \
  http://localhost:8290/api/schedules
```

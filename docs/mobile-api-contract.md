# Task Hub Mobile API Contract (v1)

## Base path
- `/api/mobile/v1`

## Public endpoints
1. `GET /health/live`
2. `GET /api/mobile/v1/meta`

## Core endpoints
1. `GET /meta`
2. `GET /session`
3. `GET /tasks`
4. `POST /tasks` (requires `Idempotency-Key`)
5. `GET /tasks/{id}`
6. `PATCH /tasks/{id}`
7. `DELETE /tasks/{id}`
8. `GET /sync/delta`
9. `GET /projects`
10. `POST /projects`
11. `GET/PATCH /me/preferences`
12. `GET/PATCH /notifications/preferences`
13. `POST /devices/register`
14. `POST /devices/unregister`
15. `PATCH/DELETE /devices/{id}`
16. `POST /intents/create-task` (requires `Idempotency-Key`)
17. `GET /widget/snapshot`

## Task payloads
1. `GET /tasks` summary items include:
   - `id`, `title`, `is_completed`, `due_at`, `updated_at`, `project`, `project_name`
2. `GET/PATCH /tasks/{id}` detail payload includes:
   - `id`, `title`, `description`, `notes`, `attachments`, `intent`, `area`, `project`, `project_name`,
     `status`, `priority`, `due_at`, `recurrence`, `completed_at`, `position`, `created_at`, `updated_at`,
     `is_completed`
3. Delta event `payload_summary` includes:
   - `title`, `is_completed`, `due_at`, `updated_at`, `project`, `project_name`

## Error envelope
All non-2xx responses return:
```json
{
  "error": {
    "code": "<machine_code>",
    "message": "<human_message>",
    "details": {}
  },
  "request_id": "<id>"
}
```

## Cursor contract
1. Sync cursor is opaque.
2. Client must store and replay cursor as-is.
3. `410 cursor_expired` indicates full-resync is required.

## Source of truth
Generated schema is versioned at:
- `backend/mobile_api/openapi/mobile-v1-openapi.json`

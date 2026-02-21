# Task Hub Mobile API Contract (v1)

## Base path
- `/api/mobile/v1`

## Core endpoints
1. `GET /meta`
2. `GET /session`
3. `GET /tasks`
4. `POST /tasks` (requires `Idempotency-Key`)
5. `GET /tasks/{id}`
6. `PATCH /tasks/{id}`
7. `DELETE /tasks/{id}`
8. `GET /sync/delta`
9. `GET/PATCH /me/preferences`
10. `GET/PATCH /notifications/preferences`
11. `POST /devices/register`
12. `PATCH/DELETE /devices/{id}`
13. `POST /intents/create-task` (requires `Idempotency-Key`)
14. `GET /widget/snapshot`

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

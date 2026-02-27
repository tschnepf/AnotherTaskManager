from __future__ import annotations

import json
from pathlib import Path


def _op(*, summary: str, scopes: list[str], request_body: bool = False) -> dict:
    operation = {
        "summary": summary,
        "security": [{"BearerAuth": scopes}] if scopes else [],
        "responses": {
            "200": {"description": "Success"},
            "400": {"description": "Client error"},
            "401": {"description": "Unauthorized"},
            "403": {"description": "Forbidden"},
        },
    }
    if request_body:
        operation["requestBody"] = {
            "required": False,
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    return operation


def generate_mobile_openapi() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Task Hub Mobile API", "version": "v1"},
        "servers": [{"url": "/"}],
        "paths": {
            "/api/mobile/v1/meta": {
                "get": _op(summary="Mobile metadata discovery", scopes=[]),
            },
            "/api/mobile/v1/session": {
                "get": _op(summary="Resolve current mobile session", scopes=["mobile.read"]),
            },
            "/api/mobile/v1/tasks": {
                "get": _op(summary="List tasks", scopes=["mobile.read"]),
                "post": _op(summary="Create task (idempotent)", scopes=["mobile.write"], request_body=True),
            },
            "/api/mobile/v1/tasks/{task_id}": {
                "get": _op(summary="Task detail", scopes=["mobile.read"]),
                "patch": _op(summary="Update task", scopes=["mobile.write"], request_body=True),
                "delete": _op(summary="Delete task", scopes=["mobile.write"]),
            },
            "/api/mobile/v1/sync/delta": {
                "get": _op(summary="Cursor-based delta sync", scopes=["mobile.sync"]),
            },
            "/api/mobile/v1/projects": {
                "get": _op(summary="List projects", scopes=["mobile.read"]),
                "post": _op(summary="Create project", scopes=["mobile.write"], request_body=True),
            },
            "/api/mobile/v1/me/preferences": {
                "get": _op(summary="Read app UI preferences", scopes=["mobile.read"]),
                "patch": _op(summary="Update app UI preferences", scopes=["mobile.write"], request_body=True),
            },
            "/api/mobile/v1/notifications/preferences": {
                "get": _op(summary="Read notification preferences", scopes=["mobile.notify"]),
                "patch": _op(summary="Update notification preferences", scopes=["mobile.notify"], request_body=True),
            },
            "/api/mobile/v1/devices/register": {
                "post": _op(summary="Register APNs device", scopes=["mobile.notify"], request_body=True),
            },
            "/api/mobile/v1/devices/unregister": {
                "post": _op(summary="Unregister APNs device", scopes=["mobile.notify"], request_body=True),
            },
            "/api/mobile/v1/devices/{device_id}": {
                "patch": _op(summary="Update APNs device", scopes=["mobile.notify"], request_body=True),
                "delete": _op(summary="Delete APNs device", scopes=["mobile.notify"]),
            },
            "/api/mobile/v1/intents/create-task": {
                "post": _op(summary="Siri create task (idempotent)", scopes=["mobile.write"], request_body=True),
            },
            "/api/mobile/v1/widget/snapshot": {
                "get": _op(summary="Widget snapshot", scopes=["mobile.read"]),
            },
            "/api/mobile/v1/admin/identity-links": {
                "post": _op(summary="Admin link identity", scopes=["mobile.read", "mobile.write"], request_body=True),
            },
            "/api/mobile/v1/admin/identity-links/{link_id}": {
                "delete": _op(summary="Admin unlink identity", scopes=["mobile.write"]),
            },
        },
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            },
            "schemas": {
                "MobileErrorEnvelope": {
                    "type": "object",
                    "required": ["error", "request_id"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message", "details"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "object"},
                            },
                        },
                        "request_id": {"type": "string"},
                    },
                }
            },
        },
    }


def render_mobile_openapi_json() -> str:
    return json.dumps(generate_mobile_openapi(), indent=2, sort_keys=True) + "\n"


def snapshot_path() -> Path:
    return Path(__file__).resolve().parent / "openapi" / "mobile-v1-openapi.json"

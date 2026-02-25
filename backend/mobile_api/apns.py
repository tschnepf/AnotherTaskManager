from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from django.conf import settings


class APNSConfigError(RuntimeError):
    pass


_APNS_JWT_TTL_SECONDS = 50 * 60
_APNS_JWT_CACHE: dict[str, tuple[str, datetime]] = {}


def validate_apns_configuration() -> None:
    if not getattr(settings, "APNS_ENABLED", False):
        return

    required = {
        "APNS_KEY_ID": getattr(settings, "APNS_KEY_ID", ""),
        "APNS_TEAM_ID": getattr(settings, "APNS_TEAM_ID", ""),
        "APNS_BUNDLE_ID": getattr(settings, "APNS_BUNDLE_ID", ""),
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        raise APNSConfigError(f"Missing APNs settings: {', '.join(missing)}")

    key_path = str(getattr(settings, "APNS_PRIVATE_KEY_PATH", "")).strip()
    key_b64 = str(getattr(settings, "APNS_PRIVATE_KEY_B64", "")).strip()
    if not key_path and not key_b64:
        raise APNSConfigError("APNS_PRIVATE_KEY_PATH or APNS_PRIVATE_KEY_B64 is required")


def _load_apns_private_key() -> str:
    key_path = str(getattr(settings, "APNS_PRIVATE_KEY_PATH", "")).strip()
    key_b64 = str(getattr(settings, "APNS_PRIVATE_KEY_B64", "")).strip()

    if key_path:
        path = Path(key_path)
        if not path.is_file():
            raise APNSConfigError(f"APNS private key file not found: {path}")
        return path.read_text(encoding="utf-8")

    try:
        decoded = base64.b64decode(key_b64, validate=True)
        return decoded.decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise APNSConfigError("APNS_PRIVATE_KEY_B64 must be valid base64-encoded UTF-8 text") from exc


def _build_provider_jwt() -> str:
    key_id = str(getattr(settings, "APNS_KEY_ID", "")).strip()
    team_id = str(getattr(settings, "APNS_TEAM_ID", "")).strip()
    if not key_id or not team_id:
        raise APNSConfigError("APNS_KEY_ID and APNS_TEAM_ID are required for APNs token auth")

    now = datetime.now(timezone.utc)
    cache_key = f"{team_id}:{key_id}"
    cached = _APNS_JWT_CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    private_key = _load_apns_private_key()
    iat = int(now.timestamp())
    exp = int((now + timedelta(seconds=_APNS_JWT_TTL_SECONDS)).timestamp())
    token = jwt.encode(
        {"iss": team_id, "iat": iat, "exp": exp},
        private_key,
        algorithm="ES256",
        headers={"alg": "ES256", "kid": key_id},
    )
    normalized = token if isinstance(token, str) else token.decode("utf-8")
    _APNS_JWT_CACHE[cache_key] = (normalized, now + timedelta(seconds=_APNS_JWT_TTL_SECONDS - 30))
    return normalized


def _apns_host() -> str:
    use_sandbox = bool(getattr(settings, "APNS_USE_SANDBOX", True))
    return "api.sandbox.push.apple.com" if use_sandbox else "api.push.apple.com"


def _normalize_apns_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    body = dict(payload or {})
    aps = body.get("aps") if isinstance(body.get("aps"), dict) else None
    payload_type = str(body.get("type") or "").strip().lower()

    if aps is not None:
        push_type = "background" if aps.get("content-available") == 1 and "alert" not in aps else "alert"
        priority = "5" if push_type == "background" else "10"
        return body, push_type, priority

    if payload_type == "task_change_sync_hint":
        apns_body = {
            "aps": {
                "content-available": 1,
            },
            "type": "task_change_sync_hint",
            "organization_id": body.get("organization_id"),
            "event_type": body.get("event_type"),
            "task_id": body.get("task_id"),
            "cursor_hint": body.get("cursor_hint"),
        }
        return apns_body, "background", "5"

    if payload_type == "task_due_reminder":
        title = str(body.get("title") or "").strip() or "Task reminder"
        due_at = str(body.get("due_at") or "").strip()
        message = f"Due {due_at}" if due_at else "Task is due soon"
        apns_body = {
            "aps": {
                "alert": {
                    "title": title,
                    "body": message,
                },
                "sound": "default",
            },
            "type": payload_type,
            "task_id": body.get("task_id"),
            "due_at": body.get("due_at"),
        }
        return apns_body, "alert", "10"

    fallback = {"aps": {"content-available": 1}, **body}
    return fallback, "background", "5"


def _build_http_client(timeout_seconds: int):
    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        raise APNSConfigError("httpx is required for APNS_PROVIDER=apns") from exc

    return httpx.Client(http2=True, timeout=timeout_seconds)


def _safe_json(response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(body, dict):
        return body
    return {"body": body}


@dataclass
class APNSDeliveryResult:
    ok: bool
    status: int
    reason: str = ""
    apns_id: str = ""
    response: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "apns_id": self.apns_id,
            "response": self.response or {},
        }


def is_dead_token_failure(result: APNSDeliveryResult) -> bool:
    if result.status == 410:
        return True
    return result.reason in {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}


def send_push_notification(*, device_token: str, payload: dict[str, Any]) -> APNSDeliveryResult:
    """
    Delivery wrapper with a mock-first provider strategy.

    APNS_PROVIDER=mock is the default to keep local/test environments deterministic.
    Production deployments should provide a real APNs implementation and set APNS_PROVIDER accordingly.
    """

    validate_apns_configuration()

    provider = str(getattr(settings, "APNS_PROVIDER", "mock")).strip().lower()
    if provider == "mock":
        return APNSDeliveryResult(ok=True, status=200, reason="mock", response={"accepted": True})
    if provider == "apns":
        normalized_token = str(device_token or "").strip()
        if not normalized_token:
            raise APNSConfigError("device_token is required")

        jwt_token = _build_provider_jwt()
        body, push_type, priority = _normalize_apns_payload(payload)
        url = f"https://{_apns_host()}/3/device/{normalized_token}"
        headers = {
            "authorization": f"bearer {jwt_token}",
            "apns-topic": str(getattr(settings, "APNS_BUNDLE_ID", "")).strip(),
            "apns-push-type": push_type,
            "apns-priority": priority,
        }

        timeout_seconds = max(1, int(getattr(settings, "APNS_REQUEST_TIMEOUT_SECONDS", 10)))
        client = _build_http_client(timeout_seconds)
        try:
            with client:
                response = client.post(url, headers=headers, json=body)
        except Exception as exc:  # noqa: BLE001
            return APNSDeliveryResult(
                ok=False,
                status=503,
                reason="transport_error",
                response={"error": str(exc)},
            )

        response_json = _safe_json(response)
        reason = str(response_json.get("reason") or "").strip()
        apns_id = str(response.headers.get("apns-id") or "").strip()
        return APNSDeliveryResult(
            ok=response.status_code == 200,
            status=response.status_code,
            reason=reason,
            apns_id=apns_id,
            response=response_json,
        )

    raise APNSConfigError(f"Unsupported APNS_PROVIDER: {provider}")

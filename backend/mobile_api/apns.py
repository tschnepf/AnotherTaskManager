from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings


class APNSConfigError(RuntimeError):
    pass


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

    raise APNSConfigError(f"Unsupported APNS_PROVIDER: {provider}")

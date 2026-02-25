import pytest
from django.test import override_settings

from mobile_api.apns import APNSConfigError, send_push_notification


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = {} if json_body is None else json_body

    def json(self):
        return self._json_body


class _FakeClient:
    def __init__(self, *, capture: dict, response: _FakeResponse | None = None, error: Exception | None = None):
        self.capture = capture
        self.response = response or _FakeResponse()
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, headers=None, json=None):
        self.capture["url"] = url
        self.capture["headers"] = dict(headers or {})
        self.capture["json"] = json
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.django_db
@override_settings(
    APNS_ENABLED=True,
    APNS_PROVIDER="apns",
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
    APNS_USE_SANDBOX=True,
)
def test_apns_provider_sends_background_push(monkeypatch):
    from mobile_api import apns as apns_mod

    apns_mod._APNS_JWT_CACHE.clear()
    capture: dict = {}
    monkeypatch.setattr(apns_mod, "_build_provider_jwt", lambda: "jwt-token")
    monkeypatch.setattr(
        apns_mod,
        "_build_http_client",
        lambda timeout_seconds: _FakeClient(
            capture=capture,
            response=_FakeResponse(status_code=200, headers={"apns-id": "apns-123"}, json_body={}),
        ),
    )

    result = send_push_notification(
        device_token="device-token-1",
        payload={"type": "task_change_sync_hint", "organization_id": "org-1", "task_id": "task-1"},
    )

    assert result.ok is True
    assert result.status == 200
    assert result.apns_id == "apns-123"
    assert capture["url"] == "https://api.sandbox.push.apple.com/3/device/device-token-1"
    assert capture["headers"]["authorization"] == "bearer jwt-token"
    assert capture["headers"]["apns-topic"] == "com.example.taskhub"
    assert capture["headers"]["apns-push-type"] == "background"
    assert capture["headers"]["apns-priority"] == "5"
    assert capture["json"]["aps"]["content-available"] == 1


@pytest.mark.django_db
@override_settings(
    APNS_ENABLED=True,
    APNS_PROVIDER="apns",
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
    APNS_USE_SANDBOX=False,
)
def test_apns_provider_sends_alert_push_and_parses_error(monkeypatch):
    from mobile_api import apns as apns_mod

    apns_mod._APNS_JWT_CACHE.clear()
    capture: dict = {}
    monkeypatch.setattr(apns_mod, "_build_provider_jwt", lambda: "jwt-token")
    monkeypatch.setattr(
        apns_mod,
        "_build_http_client",
        lambda timeout_seconds: _FakeClient(
            capture=capture,
            response=_FakeResponse(
                status_code=410,
                headers={"apns-id": "apns-410"},
                json_body={"reason": "Unregistered"},
            ),
        ),
    )

    result = send_push_notification(
        device_token="device-token-2",
        payload={"type": "task_due_reminder", "title": "Demo task", "due_at": "2026-02-24T12:00:00Z"},
    )

    assert result.ok is False
    assert result.status == 410
    assert result.reason == "Unregistered"
    assert result.apns_id == "apns-410"
    assert capture["url"] == "https://api.push.apple.com/3/device/device-token-2"
    assert capture["headers"]["apns-push-type"] == "alert"
    assert capture["headers"]["apns-priority"] == "10"
    assert capture["json"]["aps"]["alert"]["title"] == "Demo task"


@pytest.mark.django_db
@override_settings(
    APNS_ENABLED=True,
    APNS_PROVIDER="apns",
    APNS_KEY_ID="key-id",
    APNS_TEAM_ID="team-id",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="ZmFrZQ==",
)
def test_apns_provider_returns_transport_error_result(monkeypatch):
    from mobile_api import apns as apns_mod

    apns_mod._APNS_JWT_CACHE.clear()
    monkeypatch.setattr(apns_mod, "_build_provider_jwt", lambda: "jwt-token")
    monkeypatch.setattr(
        apns_mod,
        "_build_http_client",
        lambda timeout_seconds: _FakeClient(capture={}, error=RuntimeError("network unavailable")),
    )

    result = send_push_notification(device_token="device-token-3", payload={"type": "task_change_sync_hint"})

    assert result.ok is False
    assert result.status == 503
    assert result.reason == "transport_error"
    assert result.response.get("error")


@pytest.mark.django_db
@override_settings(
    APNS_ENABLED=True,
    APNS_PROVIDER="apns",
    APNS_KEY_ID="key-id-invalid",
    APNS_TEAM_ID="team-id-invalid",
    APNS_BUNDLE_ID="com.example.taskhub",
    APNS_PRIVATE_KEY_B64="not-valid-base64",
)
def test_apns_provider_rejects_invalid_base64_private_key(monkeypatch):
    from mobile_api import apns as apns_mod

    apns_mod._APNS_JWT_CACHE.clear()

    with pytest.raises(APNSConfigError):
        send_push_notification(device_token="device-token-4", payload={"type": "task_change_sync_hint"})

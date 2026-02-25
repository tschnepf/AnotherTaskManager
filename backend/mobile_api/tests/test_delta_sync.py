import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from mobile_api.sync import decode_cursor
from tasks.models import TaskChangeEvent


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_delta_sync_uses_opaque_cursor_tokens():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="sync-key-1",
    )
    res = client.get("/api/mobile/v1/sync/delta")
    assert res.status_code == 200
    assert res.data["events"]
    assert str(res.data["next_cursor"]).startswith("v1.")
    assert all(str(item["cursor"]).startswith("v1.") for item in res.data["events"])
    assert all(str(item["event_type"]).startswith("task.") for item in res.data["events"])

    follow_up = client.get("/api/mobile/v1/sync/delta", {"cursor": res.data["next_cursor"]})
    assert follow_up.status_code == 200

    # iOS URL edge case: cursor key is present but has no value (?cursor).
    no_value_cursor = client.get("/api/mobile/v1/sync/delta?cursor")
    assert no_value_cursor.status_code == 200
    assert isinstance(no_value_cursor.data["events"], list)


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_delta_sync_cursor_expired_contract():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync-expired@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    for idx in range(3):
        client.post(
            "/api/mobile/v1/tasks",
            {"title": f"Task {idx}", "area": "work"},
            format="json",
            HTTP_IDEMPOTENCY_KEY=f"sync-expired-{idx}",
        )

    first = client.get("/api/mobile/v1/sync/delta")
    first_cursor = first.data["events"][0]["cursor"]
    first_cursor_id = decode_cursor(first_cursor)

    # Simulate retention purge by removing older events.
    TaskChangeEvent.objects.filter(id__lte=first_cursor_id + 1).delete()

    expired = client.get("/api/mobile/v1/sync/delta", {"cursor": first_cursor})
    assert expired.status_code == 410
    assert expired.data["error"]["code"] == "cursor_expired"
    assert "request_id" in expired.data


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_delta_sync_invalid_cursor_is_cursor_expired():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync-invalid@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    res = client.get("/api/mobile/v1/sync/delta", {"cursor": "not-a-valid-cursor"})
    assert res.status_code == 410
    assert res.data["error"]["code"] == "cursor_expired"


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_task_summaries_and_delta_include_project_fields_after_project_change():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="sync-project@example.com", password="StrongPass123!", organization=org)
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    created = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task with project", "area": "work", "project": "ADC"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="sync-project-1",
    )
    assert created.status_code == 201
    task_id = created.data["id"]

    updated = client.patch(
        f"/api/mobile/v1/tasks/{task_id}",
        {"project": "CMH"},
        format="json",
    )
    assert updated.status_code == 200
    assert isinstance(updated.data["project"], str)
    assert updated.data["project_name"] == "CMH"

    list_res = client.get("/api/mobile/v1/tasks")
    assert list_res.status_code == 200
    task_summary = next(item for item in list_res.data if item["id"] == task_id)
    assert isinstance(task_summary["project"], str)
    assert task_summary["project_name"] == "CMH"

    delta_res = client.get("/api/mobile/v1/sync/delta", {"cursor": "0", "limit": "100"})
    assert delta_res.status_code == 200
    task_events = [item for item in delta_res.data["events"] if item["task_id"] == task_id]
    assert task_events
    assert any(
        item["event_type"] == "task.updated" and item["payload_summary"].get("project_name") == "CMH"
        for item in task_events
    )
    assert all("project" in item["payload_summary"] for item in task_events)
    assert all("project_name" in item["payload_summary"] for item in task_events)

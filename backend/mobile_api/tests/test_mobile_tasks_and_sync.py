import pytest
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Organization, User
from django.utils.dateparse import parse_datetime


@pytest.mark.django_db(transaction=True)
@override_settings(MOBILE_API_ENABLED=True, KEYCLOAK_AUTH_ENABLED=False)
def test_mobile_session_tasks_idempotency_and_delta_sync():
    org = Organization.objects.create(name="Org")
    user = User.objects.create_user(email="mobile@example.com", password="StrongPass123!", organization=org)

    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")

    session_res = client.get("/api/mobile/v1/session")
    assert session_res.status_code == 200
    assert session_res.data["organization_id"] == str(org.id)

    create_res = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="task-key-1",
    )
    assert create_res.status_code == 201
    first_task_id = create_res.data["id"]

    replay_res = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task A", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="task-key-1",
    )
    assert replay_res.status_code == 201
    assert replay_res.data["id"] == first_task_id

    conflict_res = client.post(
        "/api/mobile/v1/tasks",
        {"title": "Task B", "area": "work"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="task-key-1",
    )
    assert conflict_res.status_code == 409
    assert conflict_res.data["error"]["code"] == "idempotency_conflict"

    list_res = client.get("/api/mobile/v1/tasks")
    assert list_res.status_code == 200
    assert isinstance(list_res.data, list)
    assert list_res.data
    assert {"id", "title", "is_completed", "due_at"}.issubset(set(list_res.data[0].keys()))
    assert isinstance(list_res.data[0]["is_completed"], bool)
    if list_res.data[0]["due_at"]:
        assert "." not in list_res.data[0]["due_at"]
        assert list_res.data[0]["due_at"].endswith("Z")
        assert parse_datetime(list_res.data[0]["due_at"]) is not None

    delta_res = client.get("/api/mobile/v1/sync/delta", {"cursor": "0", "limit": "100"})
    assert delta_res.status_code == 200
    assert isinstance(delta_res.data["events"], list)
    assert any(item["task_id"] == first_task_id for item in delta_res.data["events"])
    assert isinstance(delta_res.data["next_cursor"], str)
    if delta_res.data["events"]:
        assert "." not in delta_res.data["events"][0]["occurred_at"]
        assert delta_res.data["events"][0]["occurred_at"].endswith("Z")
        assert parse_datetime(delta_res.data["events"][0]["occurred_at"]) is not None

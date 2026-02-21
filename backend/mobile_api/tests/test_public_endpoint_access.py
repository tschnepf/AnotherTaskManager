import pytest
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=True,
    KEYCLOAK_AUTH_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
)
def test_health_and_meta_are_public_tasks_requires_auth():
    client = APIClient()

    health = client.get("/health/live")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    meta = client.get("/api/mobile/v1/meta")
    assert meta.status_code == 200
    assert meta.data["api_version"] == "1"

    tasks = client.get("/api/mobile/v1/tasks")
    assert tasks.status_code == 401


@pytest.mark.django_db
@override_settings(
    MOBILE_API_ENABLED=False,
    KEYCLOAK_AUTH_ENABLED=True,
    KEYCLOAK_PUBLIC_BASE_URL="https://tasks.example.com",
    KEYCLOAK_REALM="taskhub",
)
def test_meta_is_public_even_when_mobile_api_is_disabled():
    client = APIClient()

    meta = client.get("/api/mobile/v1/meta")
    assert meta.status_code == 200
    assert meta.data["api_version"] == "1"

    tasks = client.get("/api/mobile/v1/tasks")
    assert tasks.status_code in {401, 403}
